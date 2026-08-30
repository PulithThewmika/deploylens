import { describe, it, expect, vi, beforeEach } from "vitest";
import { queryOne } from "../clients/postgres.js";
import { getSafetyScore } from "./get_safety_score.js";
import { parseResult } from "./test-utils.js";

vi.mock("../clients/postgres.js", () => ({
  queryOne: vi.fn(),
}));

const mockedQueryOne = vi.mocked(queryOne);

const makeRow = (overrides: Partial<Record<string, unknown>> = {}) => ({
  deploy_id: 5,
  deploy_status: "building",
  service_name: "orders",
  score: 40,
  risk_factors: {
    cfr_30d: { value: 0.2, threshold: 0.15, points: 25 },
    files_changed: { value: 45, threshold: 30, points: 20 },
    day_of_week: { value: "Wednesday", points: 0 },
    time_of_day: { value: "14:00", points: 0 },
    cluster_utilization: { cpu_pct: 30, mem_pct: 40, points: 0 },
    last_deploy_verdict: { value: "healthy", points: 0 },
  },
  computed_at: new Date("2026-08-29T10:20:00Z"),
  ...overrides,
});

beforeEach(() => {
  mockedQueryOne.mockReset();
});

describe("getSafetyScore", () => {
  it("returns the score, risk factor breakdown, and a summary on the happy path", async () => {
    mockedQueryOne.mockResolvedValue(makeRow());

    const result = await getSafetyScore({ deployment_id: 5 });
    const parsed = parseResult(result);

    expect(parsed.summary).toBe("orders deployment #5 — pre-deploy safety score 40/100 (rule-based, not ML)");
    expect(parsed.safety.score).toBe(40);
    expect(parsed.safety.risk_factors.cfr_30d).toMatchObject({ points: 25 });
    expect(parsed.safety.risk_factors.files_changed).toMatchObject({ points: 20 });
  });

  it("returns an error when the deployment ID does not exist", async () => {
    mockedQueryOne.mockResolvedValue(null);

    const result = await getSafetyScore({ deployment_id: 999 });
    const parsed = parseResult(result);

    expect(parsed).toEqual({
      error: "Deployment 999 not found",
      summary: "get_safety_score failed: deployment 999 not found",
    });
  });

  it("returns an informational message with current status when no safety score exists", async () => {
    mockedQueryOne.mockResolvedValue(
      makeRow({ score: null, risk_factors: null, computed_at: null, deploy_status: "deployed" }),
    );

    const result = await getSafetyScore({ deployment_id: 5 });
    const parsed = parseResult(result);

    expect(parsed.safety).toBeNull();
    expect(parsed.summary).toContain("has no safety score");
    expect(parsed.summary).toContain("deployed");
  });
});
