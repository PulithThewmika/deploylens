import { describe, it, expect, vi, beforeEach } from "vitest";
import { queryOne } from "../clients/postgres.js";
import { getDeployHealth } from "./get_deploy_health.js";

vi.mock("../clients/postgres.js", () => ({
  queryOne: vi.fn(),
}));

const mockedQueryOne = vi.mocked(queryOne);

const makeRow = (overrides: Partial<Record<string, unknown>> = {}) => ({
  deploy_id: 5,
  deploy_status: "deployed",
  service_name: "orders",
  score: 92,
  verdict: "healthy",
  assessed_at: new Date("2026-08-29T10:20:00Z"),
  error_rate_base: 0.01,
  error_rate_post: 0.012,
  latency_p99_base_ms: 100,
  latency_p99_post_ms: 110,
  restarts_base: 0,
  restarts_post: 0,
  details: {},
  ...overrides,
});

function parseResult(result: { content: { type: "text"; text: string }[] }) {
  return JSON.parse(result.content[0].text);
}

beforeEach(() => {
  mockedQueryOne.mockReset();
});

describe("getDeployHealth", () => {
  it("returns health score, verdict, evidence breakdown and a summary on the happy path", async () => {
    mockedQueryOne.mockResolvedValue(makeRow());

    const result = await getDeployHealth({ deployment_id: 5 });
    const parsed = parseResult(result);

    expect(parsed.summary).toBe("orders deployment #5 — health score 92/100 (healthy)");
    expect(parsed.health).toMatchObject({ score: 92, verdict: "healthy" });
    expect(parsed.evidence).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ metric: "error_rate", baseline: 0.01, post: 0.012 }),
        expect.objectContaining({ metric: "latency_p99", baseline: 100, post: 110 }),
        expect.objectContaining({ metric: "restarts", baseline: 0, post: 0 }),
      ]),
    );
  });

  it("returns an error when the deployment ID does not exist", async () => {
    mockedQueryOne.mockResolvedValue(null);

    const result = await getDeployHealth({ deployment_id: 999 });
    const parsed = parseResult(result);

    expect(parsed).toEqual({
      error: "Deployment 999 not found",
      summary: "get_deploy_health failed: deployment 999 not found",
    });
  });

  it("returns an informational message with current status when not yet assessed", async () => {
    mockedQueryOne.mockResolvedValue(
      makeRow({ score: null, verdict: null, assessed_at: null, deploy_status: "syncing" }),
    );

    const result = await getDeployHealth({ deployment_id: 5 });
    const parsed = parseResult(result);

    expect(parsed.health).toBeNull();
    expect(parsed.summary).toContain("has not been assessed yet");
    expect(parsed.summary).toContain("syncing");
  });

  it("surfaces guard-rail skip reasons in the evidence/details under low traffic", async () => {
    mockedQueryOne.mockResolvedValue(
      makeRow({
        error_rate_base: null,
        error_rate_post: null,
        latency_p99_base_ms: null,
        latency_p99_post_ms: null,
        details: { skipped: ["error_rate", "latency_p99"], reason: "request volume below 0.1 rps" },
      }),
    );

    const result = await getDeployHealth({ deployment_id: 5 });
    const parsed = parseResult(result);

    expect(parsed.health.details.reason).toContain("request volume below 0.1 rps");
    const errorRateEvidence = parsed.evidence.find((e: { metric: string }) => e.metric === "error_rate");
    expect(errorRateEvidence).toBeUndefined();
    const restartsEvidence = parsed.evidence.find((e: { metric: string }) => e.metric === "restarts");
    expect(restartsEvidence).toMatchObject({ baseline: 0, post: 0 });
  });
});
