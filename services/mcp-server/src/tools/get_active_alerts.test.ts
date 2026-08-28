import { describe, it, expect } from "vitest";
import { buildSummary } from "./get_active_alerts.js";

const makeAlert = (overrides: Partial<{
  id: number;
  deployment_id: number;
  service_name: string;
  severity: string;
  title: string;
  description: string | null;
  fired_at: string;
}> = {}) => ({
  id: 1,
  deployment_id: 10,
  service_name: "orders",
  severity: "warning",
  title: "High error rate",
  description: null,
  fired_at: "2026-08-29T10:00:00Z",
  ...overrides,
});

describe("buildSummary", () => {
  it("returns no-alerts message when empty", () => {
    expect(buildSummary([])).toBe("No active alerts");
  });

  it("returns no-alerts with filters", () => {
    expect(buildSummary([], "orders", "critical")).toBe(
      "No active alerts (service=orders, severity=critical)",
    );
  });

  it("summarizes single alert", () => {
    const alerts = [makeAlert()];
    const s = buildSummary(alerts);
    expect(s).toBe("1 active alert(s): 1 for orders");
  });

  it("summarizes multiple alerts across services", () => {
    const alerts = [
      makeAlert({ service_name: "orders", severity: "critical" }),
      makeAlert({ id: 2, service_name: "orders", severity: "warning" }),
      makeAlert({ id: 3, service_name: "payments", severity: "critical" }),
    ];
    const s = buildSummary(alerts);
    expect(s).toBe("3 active alert(s) (2 critical): 2 for orders, 1 for payments");
  });

  it("omits critical count when none critical", () => {
    const alerts = [
      makeAlert({ severity: "warning" }),
      makeAlert({ id: 2, service_name: "payments", severity: "warning" }),
    ];
    const s = buildSummary(alerts);
    expect(s).toBe("2 active alert(s): 1 for orders, 1 for payments");
  });
});
