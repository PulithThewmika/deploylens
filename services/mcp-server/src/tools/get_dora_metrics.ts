import { z } from "zod";
import { query } from "../clients/postgres.js";

const PERIODS = ["24h", "7d", "30d", "90d"] as const;

const PERIOD_DAYS: Record<string, number> = {
  "24h": 1,
  "7d": 7,
  "30d": 30,
  "90d": 90,
};

export const getDoraMetricsSchema = {
  service: z
    .string()
    .optional()
    .describe("Service name filter (omit for platform-wide)"),
  period: z
    .enum(PERIODS)
    .default("30d")
    .describe("Time period for aggregation (default 30d)"),
};

interface DoraResult {
  deploy_frequency_per_day: number | null;
  lead_time_avg_seconds: number | null;
  change_failure_rate: number | null;
  mttr_seconds: number | null;
}

async function queryDora(
  service: string | undefined,
  days: number,
): Promise<DoraResult> {
  const svcFilter = service ? "AND service_name = $2" : "";
  const params: unknown[] = [days];
  if (service) params.push(service);

  const [freqRows, ltRows, cfrRows, mttrRows] = await Promise.all([
    query<{ freq: number | null }>(
      `SELECT COALESCE(SUM(deploy_count)::float / NULLIF($1, 0), NULL) AS freq
       FROM dora_deploy_frequency
       WHERE deploy_date >= CURRENT_DATE - $1 * interval '1 day'
       ${svcFilter}`,
      params,
    ),
    query<{ lt: number | null }>(
      `SELECT AVG(lead_time_seconds) AS lt
       FROM dora_lead_time
       WHERE finished_at >= now() - $1 * interval '1 day'
       ${svcFilter}`,
      params,
    ),
    query<{ cfr: number | null }>(
      `SELECT ROUND(
         COUNT(*) FILTER (WHERE is_failure)::numeric
         / NULLIF(COUNT(*), 0),
         4
       ) AS cfr
       FROM dora_change_failure_rate
       WHERE started_at >= now() - $1 * interval '1 day'
       ${svcFilter}`,
      params,
    ),
    query<{ mttr: number | null }>(
      `SELECT AVG(mttr_seconds) AS mttr
       FROM dora_mttr
       WHERE fired_at >= now() - $1 * interval '1 day'
       ${svcFilter}`,
      params,
    ),
  ]);

  return {
    deploy_frequency_per_day: freqRows[0]?.freq ?? null,
    lead_time_avg_seconds: ltRows[0]?.lt ?? null,
    change_failure_rate: cfrRows[0]?.cfr != null ? Number(cfrRows[0].cfr) : null,
    mttr_seconds: mttrRows[0]?.mttr ?? null,
  };
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  return `${(seconds / 3600).toFixed(1)}h`;
}

export function buildSummary(
  result: DoraResult,
  service: string | undefined,
  period: string,
): string {
  const parts: string[] = [];

  if (result.deploy_frequency_per_day != null) {
    parts.push(`Deploys ${result.deploy_frequency_per_day.toFixed(1)}/day`);
  }
  if (result.lead_time_avg_seconds != null) {
    parts.push(`lead time ${formatDuration(result.lead_time_avg_seconds)}`);
  }
  if (result.change_failure_rate != null) {
    parts.push(`CFR ${(result.change_failure_rate * 100).toFixed(1)}%`);
  }
  if (result.mttr_seconds != null) {
    parts.push(`MTTR ${formatDuration(result.mttr_seconds)}`);
  }

  if (parts.length === 0) {
    const scope = service ? `for ${service}` : "platform-wide";
    return `No DORA data available ${scope} in the last ${period}`;
  }

  const scope = service ? ` for ${service}` : "";
  return `${parts.join(", ")}${scope} (${period})`;
}

export async function getDoraMetrics(input: {
  service?: string;
  period: string;
}): Promise<{ content: { type: "text"; text: string }[] }> {
  const days = PERIOD_DAYS[input.period] ?? 30;

  let result: DoraResult;
  try {
    result = await queryDora(input.service, days);
  } catch (err) {
    return {
      content: [{
        type: "text",
        text: JSON.stringify({
          error: `Database query failed: ${err instanceof Error ? err.message : String(err)}`,
          summary: `get_dora_metrics failed: PostgreSQL unreachable or query error`,
        }),
      }],
    };
  }

  const summary = buildSummary(result, input.service, input.period);

  return {
    content: [{
      type: "text",
      text: JSON.stringify({
        summary,
        ...result,
        period: input.period,
        service: input.service ?? null,
      }),
    }],
  };
}
