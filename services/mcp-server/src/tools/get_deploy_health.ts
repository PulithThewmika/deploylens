import { z } from "zod";
import { queryOne } from "../clients/postgres.js";

export const getDeployHealthSchema = {
  deployment_id: z.number().int().describe("Deployment ID"),
};

interface HealthRow {
  deploy_id: number;
  deploy_status: string;
  service_name: string;
  score: number | null;
  verdict: string | null;
  assessed_at: Date | null;
  error_rate_base: number | null;
  error_rate_post: number | null;
  latency_p99_base_ms: number | null;
  latency_p99_post_ms: number | null;
  restarts_base: number | null;
  restarts_post: number | null;
  details: Record<string, unknown> | null;
}

interface EvidenceItem {
  metric: string;
  baseline: number | null;
  post: number | null;
  change_pct: number | null;
}

function buildEvidence(row: HealthRow): EvidenceItem[] {
  const evidence: EvidenceItem[] = [];

  const pairs: [string, number | null, number | null][] = [
    ["error_rate", row.error_rate_base, row.error_rate_post],
    ["latency_p99", row.latency_p99_base_ms, row.latency_p99_post_ms],
    ["restarts", row.restarts_base, row.restarts_post],
  ];

  for (const [metric, baseline, post] of pairs) {
    if (baseline == null && post == null) continue;

    let changePct: number | null = null;
    if (baseline != null && post != null && baseline > 0) {
      changePct = Math.round(((post - baseline) / baseline) * 1000) / 10;
    }

    evidence.push({ metric, baseline, post, change_pct: changePct });
  }

  return evidence;
}

export async function getDeployHealth(input: {
  deployment_id: number;
}): Promise<{ content: { type: "text"; text: string }[] }> {
  const row = await queryOne<HealthRow>(
    `SELECT d.id AS deploy_id, d.status AS deploy_status,
            s.name AS service_name,
            ha.score, ha.verdict, ha.assessed_at,
            ha.error_rate_base, ha.error_rate_post,
            ha.latency_p99_base_ms, ha.latency_p99_post_ms,
            ha.restarts_base, ha.restarts_post,
            ha.details
     FROM deployments d
     JOIN services s ON s.id = d.service_id
     LEFT JOIN health_assessments ha ON ha.deployment_id = d.id
     WHERE d.id = $1`,
    [input.deployment_id],
  );

  if (!row) {
    return {
      content: [
        {
          type: "text",
          text: JSON.stringify({
            error: `Deployment ${input.deployment_id} not found`,
            summary: `get_deploy_health failed: deployment ${input.deployment_id} not found`,
          }),
        },
      ],
    };
  }

  if (row.score == null) {
    return {
      content: [
        {
          type: "text",
          text: JSON.stringify({
            summary: `Deployment #${input.deployment_id} (${row.service_name}) has not been assessed yet — current status: ${row.deploy_status}`,
            deployment_id: input.deployment_id,
            service: row.service_name,
            health: null,
          }),
        },
      ],
    };
  }

  const evidence = buildEvidence(row);

  const summary = `${row.service_name} deployment #${input.deployment_id} — health score ${row.score}/100 (${row.verdict})`;

  return {
    content: [
      {
        type: "text",
        text: JSON.stringify({
          summary,
          deployment_id: input.deployment_id,
          service: row.service_name,
          health: {
            score: row.score,
            verdict: row.verdict,
            assessed_at: row.assessed_at,
            details: row.details,
          },
          evidence,
        }),
      },
    ],
  };
}
