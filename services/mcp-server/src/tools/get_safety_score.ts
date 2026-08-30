import { z } from "zod";
import { queryOne } from "../clients/postgres.js";

export const getSafetyScoreSchema = {
  deployment_id: z.number().int().describe("Deployment ID"),
};

interface SafetyScoreRow {
  deploy_id: number;
  deploy_status: string;
  service_name: string;
  score: number | null;
  risk_factors: Record<string, unknown> | null;
  computed_at: Date | null;
}

export async function getSafetyScore(input: {
  deployment_id: number;
}): Promise<{ content: { type: "text"; text: string }[] }> {
  const row = await queryOne<SafetyScoreRow>(
    `SELECT d.id AS deploy_id, d.status AS deploy_status,
            s.name AS service_name,
            ss.score, ss.risk_factors, ss.computed_at
     FROM deployments d
     JOIN services s ON s.id = d.service_id
     LEFT JOIN safety_scores ss ON ss.deployment_id = d.id
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
            summary: `get_safety_score failed: deployment ${input.deployment_id} not found`,
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
            summary: `Deployment #${input.deployment_id} (${row.service_name}) has no safety score — current status: ${row.deploy_status}`,
            deployment_id: input.deployment_id,
            service: row.service_name,
            safety: null,
          }),
        },
      ],
    };
  }

  const summary = `${row.service_name} deployment #${input.deployment_id} — pre-deploy safety score ${row.score}/100 (rule-based, not ML)`;

  return {
    content: [
      {
        type: "text",
        text: JSON.stringify({
          summary,
          deployment_id: input.deployment_id,
          service: row.service_name,
          safety: {
            score: row.score,
            computed_at: row.computed_at,
            risk_factors: row.risk_factors,
          },
        }),
      },
    ],
  };
}
