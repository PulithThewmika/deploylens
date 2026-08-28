import { z } from "zod";
import { queryOne } from "../clients/postgres.js";
import { rangeQuery, type PromRangeResult } from "../clients/prometheus.js";

const METRIC_NAMES = [
  "error_rate",
  "latency_p99",
  "cpu",
  "memory",
  "restarts",
  "request_rate",
] as const;

type MetricName = (typeof METRIC_NAMES)[number];

export const queryMetricsSchema = {
  service: z.string().describe("Service name (must exist in the services table)"),
  metric: z
    .enum(METRIC_NAMES)
    .describe("Metric to query: error_rate, latency_p99, cpu, memory, restarts, request_rate"),
  from: z
    .string()
    .describe("Start time — relative (e.g. '-1h', '-30m') or ISO8601 timestamp"),
  to: z
    .string()
    .optional()
    .describe("End time — relative or ISO8601 (default: 'now')"),
  step: z
    .string()
    .optional()
    .describe("Step interval (e.g. '15s', '1m', '5m'). Defaults to auto-calculated"),
};

// ── Metric → unit mapping ──────────────────────────────────────

const METRIC_UNITS: Record<MetricName, string> = {
  error_rate: "fraction",
  latency_p99: "ms",
  cpu: "cores",
  memory: "bytes",
  restarts: "count",
  request_rate: "req/s",
};

// ── PromQL builders (doc 05 canonical) ─────────────────────────

export function sanitizeLabel(value: string): string {
  return value.replace(/[\\"\n\r]/g, (m) => "\\" + m);
}

export function buildPromQL(
  metric: MetricName,
  service: string,
  namespace: string,
  window: string,
): string {
  const svc = sanitizeLabel(service);
  const ns = sanitizeLabel(namespace);

  switch (metric) {
    case "error_rate":
      return (
        `sum(rate(http_requests_total{service="${svc}",` +
        `namespace="${ns}",status=~"5.."}[${window}]))` +
        ` / ` +
        `sum(rate(http_requests_total{service="${svc}",` +
        `namespace="${ns}"}[${window}]))`
      );
    case "latency_p99":
      return (
        `histogram_quantile(0.99,` +
        `sum(rate(http_request_duration_seconds_bucket{service="${svc}",` +
        `namespace="${ns}"}[${window}])) by (le))`
      );
    case "cpu":
      return (
        `sum(rate(container_cpu_usage_seconds_total` +
        `{namespace="${ns}",container="${svc}"}[${window}]))`
      );
    case "memory":
      return (
        `sum(container_memory_working_set_bytes` +
        `{namespace="${ns}",container="${svc}"})`
      );
    case "restarts":
      return (
        `sum(increase(kube_pod_container_status_restarts_total` +
        `{namespace="${ns}",container="${svc}"}[${window}]))`
      );
    case "request_rate":
      return (
        `sum(rate(http_requests_total{service="${svc}",` +
        `namespace="${ns}"}[${window}]))`
      );
  }
}

// ── Time parsing ───────────────────────────────────────────────

const RELATIVE_RE = /^-(\d+)([smhd])$/;

export function parseRelativeSeconds(rel: string): number | null {
  const match = rel.match(RELATIVE_RE);
  if (!match) return null;
  const val = parseInt(match[1], 10);
  switch (match[2]) {
    case "s": return val;
    case "m": return val * 60;
    case "h": return val * 3600;
    case "d": return val * 86400;
    default: return null;
  }
}

export function resolveTimestamp(input: string, nowEpoch: number): string {
  if (input === "now") return nowEpoch.toString();

  const relSec = parseRelativeSeconds(input);
  if (relSec != null) return (nowEpoch - relSec).toString();

  const parsed = Date.parse(input);
  if (!Number.isNaN(parsed)) return (parsed / 1000).toString();

  throw new Error(`Cannot parse time string: "${input}"`);
}

export function autoStep(startEpoch: number, endEpoch: number): string {
  const range = endEpoch - startEpoch;
  if (range <= 3600) return "15s";
  if (range <= 21600) return "1m";
  if (range <= 86400) return "5m";
  return "15m";
}

function inferRateWindow(startEpoch: number, endEpoch: number): string {
  const range = endEpoch - startEpoch;
  if (range <= 600) return "1m";
  if (range <= 3600) return "5m";
  if (range <= 21600) return "10m";
  return "15m";
}

// ── Response formatting ────────────────────────────────────────

interface DataPoint {
  t: string;
  v: number;
}

export function formatResults(
  results: PromRangeResult[],
  metric: MetricName,
): DataPoint[] {
  if (results.length === 0) return [];

  const values = results[0].values;
  return values.map(([epoch, val]) => {
    let v = parseFloat(val);
    if (metric === "latency_p99") v = v * 1000;
    return {
      t: new Date(epoch * 1000).toISOString(),
      v: Number.isNaN(v) ? 0 : Math.round(v * 1e6) / 1e6,
    };
  });
}

function buildSummary(
  service: string,
  metric: MetricName,
  points: DataPoint[],
  fromStr: string,
  toStr: string,
): string {
  if (points.length === 0) {
    return `No data for ${metric} on ${service} from ${fromStr} to ${toStr}`;
  }

  let sum = 0;
  let max = -Infinity;
  for (const p of points) {
    sum += p.v;
    if (p.v > max) max = p.v;
  }
  const avg = sum / points.length;
  const unit = METRIC_UNITS[metric];

  const fmtAvg = formatValue(avg, metric);
  const fmtMax = formatValue(max, metric);

  return (
    `${metric} for ${service}: avg ${fmtAvg}, ` +
    `max ${fmtMax} over ${points.length} samples (${fromStr} to ${toStr})`
  );
}

function formatValue(v: number, metric: MetricName): string {
  switch (metric) {
    case "error_rate":
      return (v * 100).toFixed(2) + "%";
    case "latency_p99":
      return v.toFixed(1);
    case "memory":
      return (v / 1024 / 1024).toFixed(1) + "Mi";
    case "cpu":
      return v.toFixed(3);
    case "restarts":
      return v.toFixed(0);
    case "request_rate":
      return v.toFixed(2);
  }
}

// ── Service lookup ─────────────────────────────────────────────

interface ServiceRow {
  name: string;
  namespace: string;
}

async function resolveService(name: string): Promise<ServiceRow | null> {
  return queryOne<ServiceRow>(
    `SELECT name, namespace FROM services WHERE name = $1`,
    [name],
  );
}

// ── Main handler ───────────────────────────────────────────────

export async function queryMetrics(input: {
  service: string;
  metric: MetricName;
  from: string;
  to?: string;
  step?: string;
}): Promise<{ content: { type: "text"; text: string }[] }> {
  const svc = await resolveService(input.service);
  if (!svc) {
    return {
      content: [{
        type: "text",
        text: JSON.stringify({ error: `Service "${input.service}" not found` }),
      }],
    };
  }

  const nowEpoch = Date.now() / 1000;
  const fromStr = input.from;
  const toStr = input.to ?? "now";

  let startEpoch: number;
  let endEpoch: number;
  try {
    startEpoch = parseFloat(resolveTimestamp(fromStr, nowEpoch));
    endEpoch = parseFloat(resolveTimestamp(toStr, nowEpoch));
  } catch (err) {
    return {
      content: [{
        type: "text",
        text: JSON.stringify({
          error: `Invalid time: ${err instanceof Error ? err.message : String(err)}`,
        }),
      }],
    };
  }

  if (startEpoch >= endEpoch) {
    return {
      content: [{
        type: "text",
        text: JSON.stringify({ error: "'from' must be before 'to'" }),
      }],
    };
  }

  const step = input.step ?? autoStep(startEpoch, endEpoch);
  const rateWindow = inferRateWindow(startEpoch, endEpoch);
  const promql = buildPromQL(input.metric, svc.name, svc.namespace, rateWindow);

  let results: PromRangeResult[];
  try {
    results = await rangeQuery(
      promql,
      startEpoch.toString(),
      endEpoch.toString(),
      step,
    );
  } catch (err) {
    return {
      content: [{
        type: "text",
        text: JSON.stringify({
          error: `Prometheus query failed: ${err instanceof Error ? err.message : String(err)}`,
        }),
      }],
    };
  }

  const points = formatResults(results, input.metric);
  const summary = buildSummary(svc.name, input.metric, points, fromStr, toStr);

  return {
    content: [{
      type: "text",
      text: JSON.stringify({
        summary,
        service: svc.name,
        metric: input.metric,
        unit: METRIC_UNITS[input.metric],
        promql,
        from: fromStr,
        to: toStr,
        step,
        data: points,
      }),
    }],
  };
}
