import { describe, it, expect, vi, beforeEach } from "vitest";
import { query } from "../clients/postgres.js";
import { instantQuery } from "../clients/prometheus.js";
import { compareDeploys } from "./compare_deploys.js";
import { parseResult } from "./test-utils.js";

vi.mock("../clients/postgres.js", () => ({
  query: vi.fn(),
}));

vi.mock("../clients/prometheus.js", () => ({
  instantQuery: vi.fn(),
}));

const mockedQuery = vi.mocked(query);
const mockedInstantQuery = vi.mocked(instantQuery);

const makeRow = (overrides: Partial<Record<string, unknown>> = {}) => ({
  id: 1,
  service_id: 1,
  service_name: "orders",
  namespace: "deploylens",
  status: "deployed",
  finished_at: new Date("2026-08-29T10:00:00Z"),
  commit_sha: "abc123",
  image_tag: "v1.2.3",
  health_score: 92,
  health_verdict: "healthy",
  ...overrides,
});

beforeEach(() => {
  mockedQuery.mockReset();
  mockedInstantQuery.mockReset();
});

describe("compareDeploys", () => {
  it("returns a side-by-side comparison with a summary on the happy path", async () => {
    mockedQuery.mockResolvedValue([
      makeRow({ id: 1, health_score: 92, health_verdict: "healthy" }),
      makeRow({ id: 2, health_score: 60, health_verdict: "degraded" }),
    ]);
    mockedInstantQuery.mockResolvedValue([
      { metric: {}, value: [1700000000, "0.02"] },
    ]);

    const result = await compareDeploys({ deployment_id_a: 1, deployment_id_b: 2 });
    const parsed = parseResult(result);

    expect(parsed.summary).toContain("Comparing orders deploys #1");
    expect(parsed.summary).toContain("92/100 (healthy)");
    expect(parsed.summary).toContain("60/100 (degraded)");
    expect(parsed.metrics).toHaveLength(3);
    expect(parsed.deploy_a.health_score).toBe(92);
    expect(parsed.deploy_b.health_score).toBe(60);
  });

  it("returns an error when one deployment is not found", async () => {
    mockedQuery.mockResolvedValue([makeRow({ id: 1 })]);

    const result = await compareDeploys({ deployment_id_a: 1, deployment_id_b: 999 });
    const parsed = parseResult(result);

    expect(parsed).toEqual({
      error: "Deployment 999 not found",
      summary: "compare_deploys failed: deployment 999 not found",
    });
  });

  it("returns an error when deployments belong to different services", async () => {
    mockedQuery.mockResolvedValue([
      makeRow({ id: 1, service_id: 1, service_name: "orders" }),
      makeRow({ id: 2, service_id: 2, service_name: "payments" }),
    ]);

    const result = await compareDeploys({ deployment_id_a: 1, deployment_id_b: 2 });
    const parsed = parseResult(result);

    expect(parsed.error).toBe("Both deployments must belong to the same service");
    expect(parsed.summary).toContain("deployments belong to different services");
    expect(parsed.summary).toContain("orders vs payments");
  });

  it("returns an error when a deployment has not finished yet", async () => {
    mockedQuery.mockResolvedValue([
      makeRow({ id: 1, finished_at: null }),
      makeRow({ id: 2 }),
    ]);

    const result = await compareDeploys({ deployment_id_a: 1, deployment_id_b: 2 });
    const parsed = parseResult(result);

    expect(parsed.error).toBe("Both deployments must have finished_at timestamps");
    expect(parsed.summary).toContain("have not finished yet");
  });

  it("returns comparison with a Prometheus-unreachable warning and adapted summary", async () => {
    mockedQuery.mockResolvedValue([
      makeRow({ id: 1, health_score: 92, health_verdict: "healthy" }),
      makeRow({ id: 2, health_score: 60, health_verdict: "degraded" }),
    ]);
    mockedInstantQuery.mockRejectedValue(new Error("connection refused"));

    const result = await compareDeploys({ deployment_id_a: 1, deployment_id_b: 2 });
    const parsed = parseResult(result);

    expect(parsed.warning).toBe("Prometheus unreachable — metric values are null");
    expect(parsed.summary).toContain("Prometheus unreachable, showing DB health only");
    expect(parsed.metrics.every((m: { deploy_a: unknown; deploy_b: unknown }) => m.deploy_a === null && m.deploy_b === null)).toBe(true);
  });
});
