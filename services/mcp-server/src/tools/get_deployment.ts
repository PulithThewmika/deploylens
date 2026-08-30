import { z } from "zod";
import { queryOne } from "../clients/postgres.js";

export const getDeploymentSchema = {
  deployment_id: z.number().int().describe("Deployment ID"),
};

interface DeploymentDetailRow {
  id: number;
  service_id: number;
  service_name: string;
  namespace: string;
  repo: string | null;
  argocd_app: string | null;
  commit_sha: string | null;
  branch: string | null;
  author: string | null;
  status: string;
  image_tag: string | null;
  started_at: Date;
  finished_at: Date | null;
  commit_at: Date | null;
  build_status: string | null;
  build_duration_s: number | null;
  sync_status: string | null;
  workflow_run_id: string | null;
  argocd_revision: string | null;
  created_at: Date;
  health_score: number | null;
  health_verdict: string | null;
  assessed_at: Date | null;
}

interface TimelineStage {
  stage: string;
  at: Date | null;
  status: string;
  duration_s?: number | null;
}

function buildTimeline(row: DeploymentDetailRow): TimelineStage[] {
  const stages: TimelineStage[] = [];

  if (row.commit_at) {
    stages.push({ stage: "commit", at: row.commit_at, status: "completed" });
  }

  if (row.started_at) {
    const buildStatus =
      row.build_status ??
      (!["pending", "building", "build_failed"].includes(row.status)
        ? "completed"
        : row.status);
    stages.push({
      stage: "build",
      at: row.started_at,
      status: buildStatus,
      duration_s: row.build_duration_s,
    });
  }

  if (row.argocd_revision) {
    const syncStatus =
      row.sync_status ??
      (["deployed", "assessed"].includes(row.status)
        ? "completed"
        : "in_progress");
    stages.push({ stage: "sync", at: null, status: syncStatus });
  }

  if (row.finished_at && ["deployed", "assessed"].includes(row.status)) {
    stages.push({
      stage: "deploy",
      at: row.finished_at,
      status: "completed",
    });
  }

  if (row.assessed_at) {
    stages.push({
      stage: "assess",
      at: row.assessed_at,
      status: "completed",
    });
  }

  return stages;
}

export async function getDeployment(input: {
  deployment_id: number;
}): Promise<{ content: { type: "text"; text: string }[] }> {
  const row = await queryOne<DeploymentDetailRow>(
    `SELECT d.id, d.service_id, s.name AS service_name, s.namespace,
            s.repo, s.argocd_app,
            d.commit_sha, d.branch, d.author, d.status,
            d.image_tag, d.started_at, d.finished_at,
            d.commit_at, d.build_status, d.build_duration_s,
            d.sync_status, d.workflow_run_id, d.argocd_revision,
            d.created_at,
            ha.score AS health_score, ha.verdict AS health_verdict,
            ha.assessed_at
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
            summary: `get_deployment failed: deployment ${input.deployment_id} not found`,
          }),
        },
      ],
    };
  }

  const timeline = buildTimeline(row);

  const healthSummary =
    row.health_score != null
      ? `score ${row.health_score}/100 (${row.health_verdict})`
      : "not yet assessed";

  const summary = `${row.service_name} deployment #${row.id} — ${row.status}, health: ${healthSummary}`;

  return {
    content: [
      {
        type: "text",
        text: JSON.stringify({
          summary,
          deployment: {
            id: row.id,
            service: row.service_name,
            namespace: row.namespace,
            commit_sha: row.commit_sha,
            branch: row.branch,
            author: row.author,
            status: row.status,
            image_tag: row.image_tag,
            started_at: row.started_at,
            finished_at: row.finished_at,
            build_status: row.build_status,
            build_duration_s: row.build_duration_s,
            sync_status: row.sync_status,
            argocd_revision: row.argocd_revision,
          },
          health:
            row.health_score != null
              ? {
                  score: row.health_score,
                  verdict: row.health_verdict,
                  assessed_at: row.assessed_at,
                }
              : null,
          timeline,
        }),
      },
    ],
  };
}
