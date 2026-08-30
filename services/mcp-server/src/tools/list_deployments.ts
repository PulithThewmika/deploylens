import { z } from "zod";
import { query } from "../clients/postgres.js";

export const listDeploymentsSchema = {
  service: z.string().optional().describe("Filter by service name"),
  status: z
    .enum([
      "pending",
      "building",
      "built",
      "syncing",
      "deployed",
      "assessed",
      "build_failed",
      "sync_failed",
    ])
    .optional()
    .describe("Filter by deployment status"),
  limit: z
    .number()
    .int()
    .min(1)
    .max(50)
    .default(10)
    .describe("Max results (default 10, max 50)"),
};

interface DeploymentRow {
  id: number;
  service_name: string;
  commit_sha: string | null;
  branch: string | null;
  author: string | null;
  status: string;
  image_tag: string | null;
  started_at: Date;
  finished_at: Date | null;
  health_score: number | null;
  health_verdict: string | null;
}

export async function listDeployments(input: {
  service?: string;
  status?: string;
  limit: number;
}): Promise<{ content: { type: "text"; text: string }[] }> {
  const conditions: string[] = [];
  const params: unknown[] = [];
  let paramIndex = 1;

  if (input.service) {
    conditions.push(`s.name = $${paramIndex++}`);
    params.push(input.service);
  }

  if (input.status) {
    conditions.push(`d.status = $${paramIndex++}`);
    params.push(input.status);
  }

  const whereClause =
    conditions.length > 0 ? "WHERE " + conditions.join(" AND ") : "";

  params.push(input.limit);

  const rows = await query<DeploymentRow>(
    `SELECT d.id, s.name AS service_name,
            d.commit_sha, d.branch, d.author, d.status,
            d.image_tag, d.started_at, d.finished_at,
            ha.score AS health_score, ha.verdict AS health_verdict
     FROM deployments d
     JOIN services s ON s.id = d.service_id
     LEFT JOIN health_assessments ha ON ha.deployment_id = d.id
     ${whereClause}
     ORDER BY d.started_at DESC
     LIMIT $${paramIndex}`,
    params,
  );

  if (rows.length === 0) {
    return {
      content: [
        {
          type: "text",
          text: JSON.stringify({
            summary: "No deployments found",
            deployments: [],
          }),
        },
      ],
    };
  }

  const degradedOrFailed = rows.filter(
    (r) => r.health_verdict === "degraded" || r.health_verdict === "failed",
  );

  let summary = `${rows.length} deployment(s)`;
  if (degradedOrFailed.length > 0) {
    const issues = degradedOrFailed
      .map((r) => `${r.service_name} #${r.id} (${r.health_verdict})`)
      .join(", ");
    summary += `, ${degradedOrFailed.length} unhealthy: ${issues}`;
  }

  const deployments = rows.map((r) => ({
    id: r.id,
    service: r.service_name,
    commit_sha: r.commit_sha,
    branch: r.branch,
    author: r.author,
    status: r.status,
    image_tag: r.image_tag,
    started_at: r.started_at,
    finished_at: r.finished_at,
    health: r.health_score != null
      ? { score: r.health_score, verdict: r.health_verdict }
      : null,
  }));

  return {
    content: [
      {
        type: "text",
        text: JSON.stringify({ summary, deployments }),
      },
    ],
  };
}
