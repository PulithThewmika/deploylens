import { z } from "zod";
import { query } from "../clients/postgres.js";
import { instantQuery } from "../clients/prometheus.js";

export const compareDeploysSchema = {
  deployment_id_a: z.number().int().describe("First deployment ID"),
  deployment_id_b: z.number().int().describe("Second deployment ID"),
};

const OBSERVATION_WINDOW = process.env.OBSERVATION_WINDOW ?? "15m";

interface DeployRow {
  id: number;
  service_id: number;
  service_name: string;
  namespace: string;
  status: string;
  finished_at: Date | null;
  commit_sha: string | null;
  image_tag: string | null;
  health_score: number | null;
  health_verdict: string | null;
}

interface MetricValues {
  error_rate: number | null;
  latency_p99_ms: number | null;
  restarts: number | null;
}

interface MetricDiff {
  metric: string;
  deploy_a: number | null;
  deploy_b: number | null;
  change_pct: number | null;
}

function sanitizeLabel(value: string): string {
  return value.replace(/[\\"\n\r]/g, (m) => "\\" + m);
}

function buildPromQL(
  metric: "error_rate" | "latency_p99" | "restarts",
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
    case "restarts":
      return (
        `sum(increase(kube_pod_container_status_restarts_total` +
        `{namespace="${ns}",container="${svc}"}[${window}]))`
      );
  }
}

async function queryScalar(promql: string, time: string): Promise<number | null> {
  try {
    const results = await instantQuery(promql, time);
    if (results.length === 0) return null;
    const val = parseFloat(results[0].value[1]);
    if (Number.isNaN(val)) return null;
    return val;
  } catch {
    return null;
  }
}

async function fetchMetrics(
  service: string,
  namespace: string,
  finishedAt: Date,
): Promise<MetricValues> {
  const ts = (finishedAt.getTime() / 1000 + parseWindowSeconds(OBSERVATION_WINDOW)).toString();

  const [errorRate, latencyRaw, restarts] = await Promise.all([
    queryScalar(buildPromQL("error_rate", service, namespace, OBSERVATION_WINDOW), ts),
    queryScalar(buildPromQL("latency_p99", service, namespace, OBSERVATION_WINDOW), ts),
    queryScalar(buildPromQL("restarts", service, namespace, OBSERVATION_WINDOW), ts),
  ]);

  return {
    error_rate: errorRate,
    latency_p99_ms: latencyRaw != null ? latencyRaw * 1000 : null,
    restarts,
  };
}

function parseWindowSeconds(window: string): number {
  const match = window.match(/^(\d+)([smhd])$/);
  if (!match) return 900;
  const val = parseInt(match[1], 10);
  switch (match[2]) {
    case "s": return val;
    case "m": return val * 60;
    case "h": return val * 3600;
    case "d": return val * 86400;
    default: return 900;
  }
}

function computeChangePct(a: number | null, b: number | null): number | null {
  if (a == null || b == null) return null;
  if (a === 0) return null;
  return Math.round(((b - a) / a) * 1000) / 10;
}

export async function compareDeploys(input: {
  deployment_id_a: number;
  deployment_id_b: number;
}): Promise<{ content: { type: "text"; text: string }[] }> {
  const rows = await query<DeployRow>(
    `SELECT d.id, d.service_id, s.name AS service_name, s.namespace,
            d.status, d.finished_at, d.commit_sha, d.image_tag,
            ha.score AS health_score, ha.verdict AS health_verdict
     FROM deployments d
     JOIN services s ON s.id = d.service_id
     LEFT JOIN health_assessments ha ON ha.deployment_id = d.id
     WHERE d.id IN ($1, $2)`,
    [input.deployment_id_a, input.deployment_id_b],
  );

  const byId = new Map(rows.map((r) => [r.id, r]));
  const rowA = byId.get(input.deployment_id_a);
  const rowB = byId.get(input.deployment_id_b);

  if (!rowA) {
    return {
      content: [{ type: "text", text: JSON.stringify({ error: `Deployment ${input.deployment_id_a} not found` }) }],
    };
  }
  if (!rowB) {
    return {
      content: [{ type: "text", text: JSON.stringify({ error: `Deployment ${input.deployment_id_b} not found` }) }],
    };
  }

  if (rowA.service_id !== rowB.service_id) {
    return {
      content: [{
        type: "text",
        text: JSON.stringify({
          error: "Both deployments must belong to the same service",
          deploy_a_service: rowA.service_name,
          deploy_b_service: rowB.service_name,
        }),
      }],
    };
  }

  if (!rowA.finished_at || !rowB.finished_at) {
    return {
      content: [{
        type: "text",
        text: JSON.stringify({
          error: "Both deployments must have finished_at timestamps",
          deploy_a_finished: !!rowA.finished_at,
          deploy_b_finished: !!rowB.finished_at,
        }),
      }],
    };
  }

  let metricsA: MetricValues;
  let metricsB: MetricValues;
  let promError = false;

  try {
    [metricsA, metricsB] = await Promise.all([
      fetchMetrics(rowA.service_name, rowA.namespace, rowA.finished_at),
      fetchMetrics(rowB.service_name, rowB.namespace, rowB.finished_at),
    ]);
  } catch {
    promError = true;
    metricsA = { error_rate: null, latency_p99_ms: null, restarts: null };
    metricsB = { error_rate: null, latency_p99_ms: null, restarts: null };
  }

  const diffs: MetricDiff[] = [
    {
      metric: "error_rate",
      deploy_a: metricsA.error_rate,
      deploy_b: metricsB.error_rate,
      change_pct: computeChangePct(metricsA.error_rate, metricsB.error_rate),
    },
    {
      metric: "latency_p99",
      deploy_a: metricsA.latency_p99_ms,
      deploy_b: metricsB.latency_p99_ms,
      change_pct: computeChangePct(metricsA.latency_p99_ms, metricsB.latency_p99_ms),
    },
    {
      metric: "restarts",
      deploy_a: metricsA.restarts,
      deploy_b: metricsB.restarts,
      change_pct: computeChangePct(metricsA.restarts, metricsB.restarts),
    },
  ];

  const healthA = rowA.health_score != null
    ? `${rowA.health_score}/100 (${rowA.health_verdict})`
    : "unassessed";
  const healthB = rowB.health_score != null
    ? `${rowB.health_score}/100 (${rowB.health_verdict})`
    : "unassessed";

  const summary = promError
    ? `Comparing ${rowA.service_name} deploys #${rowA.id} vs #${rowB.id} — Prometheus unreachable, showing DB health only: ${healthA} vs ${healthB}`
    : `Comparing ${rowA.service_name} deploys #${rowA.id} (${healthA}) vs #${rowB.id} (${healthB})`;

  return {
    content: [{
      type: "text",
      text: JSON.stringify({
        summary,
        deploy_a_id: rowA.id,
        deploy_b_id: rowB.id,
        service: rowA.service_name,
        deploy_a: {
          status: rowA.status,
          commit_sha: rowA.commit_sha,
          image_tag: rowA.image_tag,
          health_score: rowA.health_score,
          health_verdict: rowA.health_verdict,
        },
        deploy_b: {
          status: rowB.status,
          commit_sha: rowB.commit_sha,
          image_tag: rowB.image_tag,
          health_score: rowB.health_score,
          health_verdict: rowB.health_verdict,
        },
        metrics: diffs,
        ...(promError ? { warning: "Prometheus unreachable — metric values are null" } : {}),
      }),
    }],
  };
}
