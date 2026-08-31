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
    mockedQueryOne
      .mockResolvedValueOnce({ id: 31, name: "sample-app", prom_components: ["frontend", "orders", "payments"] })
      .mockResolvedValueOnce({ verdict: "healthy", score: 92, assessed_at: new Date("2026-08-30T10:00:00Z") });
    mockedQuery.mockResolvedValueOnce([
      {
        source_component: "orders",
        target_component: "payments",
        dep_type: "calls",
        target_service_id: 31,
        target_service_name: "sample-app",
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
    expect(mockedQuery).toHaveBeenCalledWith(expect.any(String), [31, ["orders"]]);
  });

  it("expands to all components when a services.name is given", async () => {
    mockedQueryOne.mockResolvedValueOnce({
      id: 31,
      name: "sample-app",
      prom_components: ["frontend", "orders", "payments"],
    });
    mockedQuery.mockResolvedValueOnce([
      {
        source_component: "frontend",
        target_component: "orders",
        dep_type: "calls",
        target_service_id: 31,
        target_service_name: "sample-app",
      },
      {
        source_component: "orders",
        target_component: "payments",
        dep_type: "calls",
        target_service_id: 31,
        target_service_name: "sample-app",
      },
    ]);
    mockedQueryOne.mockResolvedValue({ verdict: "degraded", score: 60, assessed_at: new Date() });

    const result = await getBlastRadius({ service: "sample-app" });
    const parsed = parseResult(result);

    expect(parsed.queried_components).toEqual(["frontend", "orders", "payments"]);
    expect(parsed.downstream).toHaveLength(2);
    expect(parsed.summary).toContain("2 downstream component(s)");
    expect(parsed.summary).toContain("not currently healthy");
  });

  it("returns an empty downstream list with a clear summary when there are no discovered edges", async () => {
    mockedQueryOne.mockResolvedValueOnce({ id: 31, name: "sample-app", prom_components: ["payments"] });
    mockedQuery.mockResolvedValueOnce([]);

    const result = await getBlastRadius({ service: "payments" });
    const parsed = parseResult(result);

    expect(parsed.downstream).toEqual([]);
    expect(parsed.summary).toBe("payments has no discovered downstream dependencies");
  });
});
