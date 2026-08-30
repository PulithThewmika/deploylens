import { describe, it, expect } from "vitest";
import { buildSummary } from "./get_dora_metrics.js";

describe("buildSummary", () => {
  it("formats all four metrics", () => {
    const result = {
      deploy_frequency_per_day: 4.2,
      lead_time_avg_seconds: 1380,
      change_failure_rate: 0.12,
      mttr_seconds: 2700,
    };
    const s = buildSummary(result, undefined, "30d");
    expect(s).toBe("Deploys 4.2/day, lead time 23m, CFR 12.0%, MTTR 45m (30d)");
  });

  it("formats with service filter", () => {
    const result = {
      deploy_frequency_per_day: 1.0,
      lead_time_avg_seconds: 300,
      change_failure_rate: 0.0,
      mttr_seconds: null,
    };
    const s = buildSummary(result, "orders", "7d");
    expect(s).toBe("Deploys 1.0/day, lead time 5m, CFR 0.0% for orders (7d)");
  });

  it("returns no-data message when all null", () => {
    const result = {
      deploy_frequency_per_day: null,
      lead_time_avg_seconds: null,
      change_failure_rate: null,
      mttr_seconds: null,
    };
    const s = buildSummary(result, undefined, "30d");
    expect(s).toBe("No DORA data available platform-wide in the last 30d");
  });

  it("returns no-data message with service", () => {
    const result = {
      deploy_frequency_per_day: null,
      lead_time_avg_seconds: null,
      change_failure_rate: null,
      mttr_seconds: null,
    };
    const s = buildSummary(result, "payments", "7d");
    expect(s).toBe("No DORA data available for payments in the last 7d");
  });

  it("formats lead time in hours for large values", () => {
    const result = {
      deploy_frequency_per_day: 2.0,
      lead_time_avg_seconds: 7200,
      change_failure_rate: null,
      mttr_seconds: null,
    };
    const s = buildSummary(result, undefined, "90d");
    expect(s).toBe("Deploys 2.0/day, lead time 2.0h (90d)");
  });

  it("formats lead time in seconds for small values", () => {
    const result = {
      deploy_frequency_per_day: null,
      lead_time_avg_seconds: 45,
      change_failure_rate: null,
      mttr_seconds: null,
    };
    const s = buildSummary(result, undefined, "24h");
    expect(s).toBe("lead time 45s (24h)");
  });
});
