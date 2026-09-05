import { describe, it, expect, vi, beforeEach } from "vitest";
import { queryOne } from "../clients/postgres.js";
import { getDeployment } from "./get_deployment.js";
import { parseResult } from "./test-utils.js";

vi.mock("../clients/postgres.js", () => ({
  queryOne: vi.fn(),
}));

const mockedQueryOne = vi.mocked(queryOne);

const makeRow = (overrides: Partial<Record<string, unknown>> = {}) => ({
  id: 5,
  service_id: 1,
  service_name: "orders",
  namespace: "kubex",
  repo: "org/orders",
  argocd_app: "orders",
  commit_sha: "abc123",
  branch: "main",
  author: "alice",
  status: "deployed",
  image_tag: "v1.2.3",
  started_at: new Date("2026-08-29T10:00:00Z"),
  finished_at: new Date("2026-08-29T10:05:00Z"),
  commit_at: new Date("2026-08-29T09:55:00Z"),
  build_status: "completed",
  build_duration_s: 120,
  sync_status: "completed",
  workflow_run_id: "1234",
  argocd_revision: "def456",
  created_at: new Date("2026-08-29T09:55:00Z"),
  health_score: 92,
  health_verdict: "healthy",
  assessed_at: new Date("2026-08-29T10:20:00Z"),
  ...overrides,
});

beforeEach(() => {
  mockedQueryOne.mockReset();
});

describe("getDeployment", () => {
  it("returns full deployment info with service, timeline, health, and a summary", async () => {
    mockedQueryOne.mockResolvedValue(makeRow());

    const result = await getDeployment({ deployment_id: 5 });
    const parsed = parseResult(result);

    expect(parsed.summary).toBe(
      "orders deployment #5 — deployed, health: score 92/100 (healthy)",
    );
    expect(parsed.deployment).toMatchObject({
      id: 5,
      service: "orders",
      namespace: "kubex",
      status: "deployed",
    });
    expect(parsed.health).toMatchObject({ score: 92, verdict: "healthy" });
    expect(parsed.timeline.length).toBeGreaterThan(0);
    expect(parsed.timeline.map((t: { stage: string }) => t.stage)).toContain("build");
  });

  it("returns an error when the deployment ID does not exist", async () => {
    mockedQueryOne.mockResolvedValue(null);

    const result = await getDeployment({ deployment_id: 999 });
    const parsed = parseResult(result);

    expect(parsed).toEqual({
      error: "Deployment 999 not found",
      summary: "get_deployment failed: deployment 999 not found",
    });
  });

  it("shows null health_assessment and reflects status in the summary when not yet assessed", async () => {
    mockedQueryOne.mockResolvedValue(
      makeRow({ health_score: null, health_verdict: null, assessed_at: null, status: "syncing" }),
    );

    const result = await getDeployment({ deployment_id: 5 });
    const parsed = parseResult(result);

    expect(parsed.health).toBeNull();
    expect(parsed.summary).toContain("syncing");
    expect(parsed.summary).toContain("not yet assessed");
  });
});
