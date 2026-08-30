import { describe, it, expect, vi, beforeEach } from "vitest";
import { query } from "../clients/postgres.js";
import { listDeployments } from "./list_deployments.js";
import { parseResult } from "./test-utils.js";

vi.mock("../clients/postgres.js", () => ({
  query: vi.fn(),
}));

const mockedQuery = vi.mocked(query);

const makeRow = (overrides: Partial<{
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
}> = {}) => ({
  id: 1,
  service_name: "orders",
  commit_sha: "abc123",
  branch: "main",
  author: "alice",
  status: "deployed",
  image_tag: "v1.2.3",
  started_at: new Date("2026-08-29T10:00:00Z"),
  finished_at: new Date("2026-08-29T10:05:00Z"),
  health_score: 92,
  health_verdict: "healthy",
  ...overrides,
});

beforeEach(() => {
  mockedQuery.mockReset();
});

describe("listDeployments", () => {
  it("returns deployments array with a summary field on the happy path", async () => {
    mockedQuery.mockResolvedValue([makeRow()]);

    const result = await listDeployments({ limit: 10 });
    const parsed = parseResult(result);

    expect(parsed.summary).toContain("1 deployment(s)");
    expect(parsed.deployments).toHaveLength(1);
    expect(parsed.deployments[0]).toMatchObject({
      id: 1,
      service: "orders",
      status: "deployed",
      health: { score: 92, verdict: "healthy" },
    });
  });

  it("returns a 'No deployments found' summary when the result set is empty", async () => {
    mockedQuery.mockResolvedValue([]);

    const result = await listDeployments({ limit: 10 });
    const parsed = parseResult(result);

    expect(parsed).toEqual({ summary: "No deployments found", deployments: [] });
  });

  it("filters by service name", async () => {
    mockedQuery.mockResolvedValue([makeRow({ service_name: "orders" })]);

    await listDeployments({ service: "orders", limit: 10 });

    const [sql, params] = mockedQuery.mock.calls[0];
    expect(sql).toContain("s.name =");
    expect(params).toContain("orders");
  });

  it("returns an empty array when the service filter matches no service", async () => {
    mockedQuery.mockResolvedValue([]);

    const result = await listDeployments({ service: "nonexistent", limit: 10 });
    const parsed = parseResult(result);

    expect(parsed).toEqual({ summary: "No deployments found", deployments: [] });
    const [sql, params] = mockedQuery.mock.calls[0];
    expect(sql).toContain("s.name =");
    expect(params).toContain("nonexistent");
  });

  it("filters by status", async () => {
    mockedQuery.mockResolvedValue([makeRow({ status: "sync_failed" })]);

    await listDeployments({ status: "sync_failed", limit: 10 });

    const [sql, params] = mockedQuery.mock.calls[0];
    expect(sql).toContain("d.status =");
    expect(params).toContain("sync_failed");
  });

  it("highlights degraded and failed deploys in the summary string", async () => {
    mockedQuery.mockResolvedValue([
      makeRow({ id: 1, service_name: "orders", health_verdict: "healthy" }),
      makeRow({ id: 2, service_name: "payments", health_verdict: "degraded" }),
      makeRow({ id: 3, service_name: "frontend", health_verdict: "failed" }),
    ]);

    const result = await listDeployments({ limit: 10 });
    const parsed = parseResult(result);

    expect(parsed.summary).toContain("2 unhealthy");
    expect(parsed.summary).toContain("payments #2 (degraded)");
    expect(parsed.summary).toContain("frontend #3 (failed)");
  });

  it("represents deployments with no health assessment as health: null", async () => {
    mockedQuery.mockResolvedValue([makeRow({ health_score: null, health_verdict: null })]);

    const result = await listDeployments({ limit: 10 });
    const parsed = parseResult(result);

    expect(parsed.deployments[0].health).toBeNull();
  });
});
