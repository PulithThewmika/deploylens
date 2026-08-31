import { describe, it, expect, vi, beforeEach } from "vitest";
import { query, queryOne } from "../clients/postgres.js";
import { getBlastRadius } from "./get_blast_radius.js";
import { parseResult } from "./test-utils.js";

vi.mock("../clients/postgres.js", () => ({
  query: vi.fn(),
  queryOne: vi.fn(),
}));

const mockedQuery = vi.mocked(query);
const mockedQueryOne = vi.mocked(queryOne);

beforeEach(() => {
  mockedQuery.mockReset();
  mockedQueryOne.mockReset();
});

describe("getBlastRadius", () => {
  it("returns an error when the service/component is not found", async () => {
    mockedQueryOne.mockResolvedValueOnce(null);

    const result = await getBlastRadius({ service: "nonexistent" });
    const parsed = parseResult(result);

    expect(parsed).toEqual({
      error: "No service or component named 'nonexistent' found",
      summary: "get_blast_radius failed: 'nonexistent' not found",
    });
  });

  it("scopes to just the queried component when a component name is given", async () => {
    mockedQueryOne.mockResolvedValueOnce({
      id: 31,
      name: "sample-app",
      prom_components: ["frontend", "orders", "payments"],
      matched_by_name: false,
    });
    mockedQuery.mockResolvedValueOnce([
      {
        source_component: "orders",
        target_component: "payments",
        dep_type: "calls",
        target_service_id: 31,
        target_service_name: "sample-app",
        verdict: "healthy",
        score: 92,
        assessed_at: new Date("2026-08-30T10:00:00Z"),
      },
    ]);

    const result = await getBlastRadius({ service: "orders" });
    const parsed = parseResult(result);

    expect(parsed.queried_components).toEqual(["orders"]);
    expect(parsed.downstream).toHaveLength(1);
    expect(parsed.downstream[0]).toMatchObject({
      source_component: "orders",
      target_component: "payments",
      current_health: { verdict: "healthy", score: 92 },
    });
    // Single batched query, not one queryOne per edge.
    expect(mockedQueryOne).toHaveBeenCalledTimes(1);
    expect(mockedQuery).toHaveBeenCalledWith(expect.any(String), [31, ["orders"]]);
  });

  it("expands to all components when a services.name is given", async () => {
    mockedQueryOne.mockResolvedValueOnce({
      id: 31,
      name: "sample-app",
      prom_components: ["frontend", "orders", "payments"],
      matched_by_name: true,
    });
    mockedQuery.mockResolvedValueOnce([
      {
        source_component: "frontend",
        target_component: "orders",
        dep_type: "calls",
        target_service_id: 31,
        target_service_name: "sample-app",
        verdict: "degraded",
        score: 60,
        assessed_at: new Date(),
      },
      {
        source_component: "orders",
        target_component: "payments",
        dep_type: "calls",
        target_service_id: 31,
        target_service_name: "sample-app",
        verdict: "degraded",
        score: 60,
        assessed_at: new Date(),
      },
    ]);

    const result = await getBlastRadius({ service: "sample-app" });
    const parsed = parseResult(result);

    expect(parsed.queried_components).toEqual(["frontend", "orders", "payments"]);
    expect(parsed.downstream).toHaveLength(2);
    expect(parsed.summary).toContain("2 downstream component(s)");
    expect(parsed.summary).toContain("not currently healthy");
  });

  it("returns an empty downstream list with a clear summary when there are no discovered edges", async () => {
    mockedQueryOne.mockResolvedValueOnce({
      id: 31,
      name: "sample-app",
      prom_components: ["payments"],
      matched_by_name: false,
    });
    mockedQuery.mockResolvedValueOnce([]);

    const result = await getBlastRadius({ service: "payments" });
    const parsed = parseResult(result);

    expect(parsed.downstream).toEqual([]);
    expect(parsed.summary).toBe("payments has no discovered downstream dependencies");
  });

  it("prefers an exact services.name match over a prom_components collision, deterministically", async () => {
    // matched_by_name comes straight from the query/ORDER BY, so the tool
    // doesn't need to re-derive which column matched — this just checks
    // the branch follows that field rather than re-comparing strings.
    mockedQueryOne.mockResolvedValueOnce({
      id: 5,
      name: "orders",
      prom_components: ["orders-worker"],
      matched_by_name: true,
    });
    mockedQuery.mockResolvedValueOnce([]);

    const result = await getBlastRadius({ service: "orders" });
    const parsed = parseResult(result);

    expect(parsed.queried_components).toEqual(["orders-worker"]);
  });
});
