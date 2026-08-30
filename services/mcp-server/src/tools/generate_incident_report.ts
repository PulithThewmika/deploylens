import { z } from "zod";
import { queryOne } from "../clients/postgres.js";
import { rangeQuery } from "../clients/prometheus.js";
import { queryRange as lokiQueryRange, type LokiStream } from "../clients/loki.js";
import { buildPromQL, autoStep, formatResults } from "./query_metrics.js";
import { buildLogQL } from "./query_logs.js";

export const generateIncidentReportSchema = {
  alert_id: z.number().int().describe("Alert ID to generate an incident report for"),
};

interface IncidentRow {
  alert_id: number;
  severity: string;
  title: string;
  description: string | null;
  fired_at: Date;
  resolved_at: Date | null;
  alertmanager_id: string | null;
  deployment_id: number;
  commit_sha: string | null;
  branch: string | null;
  author: string | null;
  deploy_status: string;
  deploy_started_at: Date;
  deploy_finished_at: Date | null;
  image_tag: string | null;
  service_name: string;
  namespace: string;
  prom_components: string[] | null;
  score: number | null;
  verdict: string | null;
  error_rate_base: number | null;
  error_rate_post: number | null;
  latency_p99_base_ms: number | null;
  latency_p99_post_ms: number | null;
  restarts_base: number | null;
  restarts_post: number | null;
}

const METRICS = ["error_rate", "latency_p99", "restarts"] as const;
const METRIC_LABELS: Record<(typeof METRICS)[number], string> = {
  error_rate: "Error Rate",
  latency_p99: "p99 Latency (ms)",
  restarts: "Restarts",
};

function fmtTime(d: Date | string | null): string {
  if (!d) return "—";
  return new Date(d).toISOString().replace("T", " ").replace(/\.\d+Z$/, " UTC");
}

function fmtNum(v: number | null): string {
  return v == null ? "—" : v.toFixed(4);
}

// A "service" in the ingest DB can roll up several Prometheus/Loki
// components (see services.prom_components — e.g. one ArgoCD Application
// deploying frontend+orders+payments together is one ingest "service" but
// three separately-labeled components). Metrics and logs are only ever
// labeled per-component, never with the rolled-up service name, so every
// query here must run per-component and merge — querying by service_name
// directly would silently return nothing for any multi-component service.
function resolveComponents(serviceName: string, promComponents: string[] | null): string[] {
  return promComponents && promComponents.length > 0 ? promComponents : [serviceName];
}

async function fetchMetricWindow(
  components: string[],
  namespace: string,
  startEpoch: number,
  endEpoch: number,
): Promise<Record<string, { t: string; v: number }[]>> {
  const step = autoStep(startEpoch, endEpoch);
  const rateWindow = "5m";
  const result: Record<string, { t: string; v: number }[]> = {};

  for (const metric of METRICS) {
    const perComponentSeries = await Promise.all(
      components.map(async (component) => {
        const promql = buildPromQL(metric, component, namespace, rateWindow);
        try {
          const raw = await rangeQuery(promql, startEpoch.toString(), endEpoch.toString(), step);
          return formatResults(raw, metric);
        } catch {
          return [];
        }
      }),
    );

    // Same convention as the agent's health-score aggregation
    // (_aggregate_metrics): max across components for rates/latency, sum
    // for restarts.
    const byTime = new Map<string, number[]>();
    for (const series of perComponentSeries) {
      for (const point of series) {
        const values = byTime.get(point.t) ?? [];
        values.push(point.v);
        byTime.set(point.t, values);
      }
    }
    const combine = metric === "restarts"
      ? (values: number[]) => values.reduce((a, b) => a + b, 0)
      : (values: number[]) => Math.max(...values);

    result[metric] = Array.from(byTime.entries())
      .map(([t, values]) => ({ t, v: combine(values) }))
      .sort((a, b) => a.t.localeCompare(b.t));
  }
  return result;
}

async function fetchErrorLogs(
  components: string[],
  startEpoch: number,
  endEpoch: number,
): Promise<{ ts: string; line: string }[]> {
  const perComponentStreams = await Promise.all(
    components.map(async (component) => {
      const logql = buildLogQL(component, undefined, "error");
      try {
        return await lokiQueryRange(
          logql,
          (startEpoch * 1e9).toFixed(0),
          (endEpoch * 1e9).toFixed(0),
          50,
        );
      } catch {
        return [] as LokiStream[];
      }
    }),
  );

  const entries: { ts: string; line: string }[] = [];
  for (const streams of perComponentStreams) {
    for (const stream of streams) {
      for (const [tsNano, line] of stream.values) {
        const epochMs = Number(BigInt(tsNano) / 1_000_000n);
        entries.push({ ts: new Date(epochMs).toISOString(), line });
      }
    }
  }
  entries.sort((a, b) => a.ts.localeCompare(b.ts));
  return entries.slice(0, 50);
}

function buildMetricTable(series: Record<string, { t: string; v: number }[]>): string {
  const allTimestamps = new Set<string>();
  for (const metric of METRICS) {
    for (const point of series[metric]) allTimestamps.add(point.t);
  }
  if (allTimestamps.size === 0) {
    return "_No metric data available for this window._\n";
  }

  const timestamps = Array.from(allTimestamps).sort();
  const byMetricByTime: Record<string, Map<string, number>> = {};
  for (const metric of METRICS) {
    byMetricByTime[metric] = new Map(series[metric].map((p) => [p.t, p.v]));
  }

  const header = `| Time | ${METRICS.map((m) => METRIC_LABELS[m]).join(" | ")} |`;
  const divider = `| --- | ${METRICS.map(() => "---").join(" | ")} |`;
  const rows = timestamps.map((t) => {
    const cells = METRICS.map((m) => {
      const v = byMetricByTime[m].get(t);
      return v === undefined ? "—" : v.toFixed(4);
    });
    return `| ${fmtTime(t)} | ${cells.join(" | ")} |`;
  });

  return [header, divider, ...rows].join("\n") + "\n";
}

function buildMarkdownReport(row: IncidentRow, metricSeries: Record<string, { t: string; v: number }[]>, logs: { ts: string; line: string }[]): string {
  const lines: string[] = [];

  lines.push(`# Incident Report: Alert #${row.alert_id} — ${row.title}`);
  lines.push("");
  lines.push(`**Service:** ${row.service_name}  `);
  lines.push(`**Severity:** ${row.severity}  `);
  lines.push(`**Status:** ${row.resolved_at ? `Resolved at ${fmtTime(row.resolved_at)}` : "Active"}`);
  lines.push("");

  lines.push("## Deployment");
  lines.push("");
  lines.push(`- **Deployment ID:** #${row.deployment_id}`);
  lines.push(`- **Commit:** ${row.commit_sha ?? "unknown"}${row.branch ? ` (${row.branch})` : ""}`);
  lines.push(`- **Author:** ${row.author ?? "unknown"}`);
  lines.push(`- **Image tag:** ${row.image_tag ?? "unknown"}`);
  lines.push(`- **Deployed:** ${fmtTime(row.deploy_started_at)} → ${fmtTime(row.deploy_finished_at)}`);
  if (row.score != null) {
    lines.push(`- **Health score:** ${row.score}/100 (${row.verdict})`);
  }
  lines.push("");

  lines.push("## Metric Changes (baseline vs. post-deploy)");
  lines.push("");
  if (row.score != null) {
    lines.push("| Metric | Baseline | Post-Deploy |");
    lines.push("| --- | --- | --- |");
    lines.push(`| Error rate | ${fmtNum(row.error_rate_base)} | ${fmtNum(row.error_rate_post)} |`);
    lines.push(`| p99 latency (ms) | ${fmtNum(row.latency_p99_base_ms)} | ${fmtNum(row.latency_p99_post_ms)} |`);
    lines.push(`| Restarts | ${fmtNum(row.restarts_base)} | ${fmtNum(row.restarts_post)} |`);
  } else {
    lines.push("_This deployment has not been health-assessed yet._");
  }
  lines.push("");

  lines.push("## Metric Timeline");
  lines.push("");
  lines.push(buildMetricTable(metricSeries));

  lines.push("## Error Logs");
  lines.push("");
  if (logs.length === 0) {
    lines.push("_No error-level logs found in this window._");
  } else {
    lines.push("```");
    for (const log of logs) {
      lines.push(`${fmtTime(log.ts)}  ${log.line}`);
    }
    lines.push("```");
  }
  lines.push("");

  lines.push("## Alert Details");
  lines.push("");
  lines.push(`- **Fired at:** ${fmtTime(row.fired_at)}`);
  lines.push(`- **Resolved at:** ${fmtTime(row.resolved_at)}`);
  if (row.description) lines.push(`- **Description:** ${row.description}`);
  if (row.alertmanager_id) lines.push(`- **Alertmanager ID:** ${row.alertmanager_id}`);

  return lines.join("\n");
}

export async function generateIncidentReport(input: {
  alert_id: number;
}): Promise<{ content: { type: "text"; text: string }[] }> {
  const row = await queryOne<IncidentRow>(
    `SELECT
       a.id AS alert_id, a.severity, a.title, a.description, a.fired_at, a.resolved_at, a.alertmanager_id,
       d.id AS deployment_id, d.commit_sha, d.branch, d.author, d.status AS deploy_status,
       d.started_at AS deploy_started_at, d.finished_at AS deploy_finished_at, d.image_tag,
       s.name AS service_name, s.namespace, s.prom_components,
       ha.score, ha.verdict,
       ha.error_rate_base, ha.error_rate_post,
       ha.latency_p99_base_ms, ha.latency_p99_post_ms,
       ha.restarts_base, ha.restarts_post
     FROM alerts a
     JOIN deployments d ON d.id = a.deployment_id
     JOIN services s ON s.id = d.service_id
     LEFT JOIN health_assessments ha ON ha.deployment_id = d.id
     WHERE a.id = $1`,
    [input.alert_id],
  );

  if (!row) {
    return {
      content: [{
        type: "text",
        text: JSON.stringify({
          error: `Alert ${input.alert_id} not found`,
          summary: `generate_incident_report failed: alert ${input.alert_id} not found`,
        }),
      }],
    };
  }

  const deployStartEpoch = new Date(row.deploy_started_at).getTime() / 1000;
  const nowEpoch = Date.now() / 1000;
  const firedEpoch = new Date(row.fired_at).getTime() / 1000;
  const windowStart = deployStartEpoch - 5 * 60;
  const windowEnd = Math.min(Math.max(firedEpoch, deployStartEpoch) + 5 * 60, nowEpoch);
  const components = resolveComponents(row.service_name, row.prom_components);

  const [metricSeries, logs] = await Promise.all([
    fetchMetricWindow(components, row.namespace, windowStart, windowEnd),
    fetchErrorLogs(components, windowStart, windowEnd),
  ]);

  const report = buildMarkdownReport(row, metricSeries, logs);
  const summary = `Incident report for alert #${row.alert_id} (${row.service_name}, ${row.severity}) — ${report.length} chars`;

  return {
    content: [{
      type: "text",
      text: JSON.stringify({ summary, alert_id: row.alert_id, report }),
    }],
  };
}
