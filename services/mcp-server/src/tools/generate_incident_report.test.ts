import { describe, it, expect, vi, beforeEach } from "vitest";
import { queryOne } from "../clients/postgres.js";
import { rangeQuery } from "../clients/prometheus.js";
import { queryRange as lokiQueryRange } from "../clients/loki.js";
import { generateIncidentReport } from "./generate_incident_report.js";
import { parseResult } from "./test-utils.js";

vi.mock("../clients/postgres.js", () => ({
  queryOne: vi.fn(),
}));

vi.mock("../clients/prometheus.js", () => ({
  rangeQuery: vi.fn(),
}));

vi.mock("../clients/loki.js", () => ({
  queryRange: vi.fn(),
}));

const mockedQueryOne = vi.mocked(queryOne);
const mockedRangeQuery = vi.mocked(rangeQuery);
const mockedLokiQueryRange = vi.mocked(lokiQueryRange);

const makeRow = (overrides: Partial<Record<string, unknown>> = {}) => ({
  alert_id: 42,
  severity: "critical",
  title: "Deploy #10 of orders scored 35/100",
  description: "Error rate spiked after deploy",
  fired_at: new Date("2026-08-29T10:20:00Z"),
  resolved_at: null,
  alertmanager_id: "am-123",
  deployment_id: 10,
  commit_sha: "abc1234",
  branch: "main",
  author: "alice",
  deploy_status: "assessed",
  deploy_started_at: new Date("2026-08-29T10:00:00Z"),
  deploy_finished_at: new Date("2026-08-29T10:05:00Z"),
  image_tag: "abc1234",
  service_name: "orders",
  namespace: "deploylens",
  prom_components: null,
  score: 35,
  verdict: "failed",
  error_rate_base: 0.01,
  error_rate_post: 0.25,
  latency_p99_base_ms: 100,
  latency_p99_post_ms: 105,
  restarts_base: 0,
  restarts_post: 0,
  ...overrides,
});

beforeEach(() => {
  mockedQueryOne.mockReset();
  mockedRangeQuery.mockReset();
  mockedLokiQueryRange.mockReset();
});

describe("generateIncidentReport", () => {
  it("returns a meaningful markdown report for a known degraded deployment", async () => {
    mockedQueryOne.mockResolvedValue(makeRow());
    mockedRangeQuery.mockResolvedValue([
      { metric: {}, values: [[1756461600, "0.01"], [1756461900, "0.25"]] },
    ]);
    mockedLokiQueryRange.mockResolvedValue([
      {
        stream: { app: "orders" },
        values: [["1756461800000000000", "ERROR database connection timeout"]],
      },
    ]);

    const result = await generateIncidentReport({ alert_id: 42 });
    const parsed = parseResult(result);

    expect(parsed.alert_id).toBe(42);
    expect(typeof parsed.report).toBe("string");

    const report: string = parsed.report;
    expect(report).toContain("# Incident Report: Alert #42");
    expect(report).toContain("## Deployment");
    expect(report).toContain("orders");
    expect(report).toContain("abc1234");
    expect(report).toContain("## Metric Changes");
    expect(report).toContain("## Metric Timeline");
    expect(report).toContain("## Error Logs");
    expect(report).toContain("database connection timeout");
    expect(report).toContain("## Alert Details");
    expect(report).toContain("35/100");
  });

  it("returns an error when the alert ID does not exist", async () => {
    mockedQueryOne.mockResolvedValue(null);

    const result = await generateIncidentReport({ alert_id: 999 });
    const parsed = parseResult(result);

    expect(parsed).toEqual({
      error: "Alert 999 not found",
      summary: "generate_incident_report failed: alert 999 not found",
    });
  });

  it("still produces a report when the deployment has no health assessment yet", async () => {
    mockedQueryOne.mockResolvedValue(
      makeRow({ score: null, verdict: null, error_rate_base: null, error_rate_post: null }),
    );
    mockedRangeQuery.mockResolvedValue([]);
    mockedLokiQueryRange.mockResolvedValue([]);

    const result = await generateIncidentReport({ alert_id: 42 });
    const parsed = parseResult(result);

    expect(parsed.report).toContain("has not been health-assessed yet");
    expect(parsed.report).toContain("No error-level logs found");
  });

  it("aggregates metrics and logs across all prom_components, not the rolled-up service name", async () => {
    mockedQueryOne.mockResolvedValue(makeRow({ prom_components: ["frontend", "orders", "payments"] }));

    mockedRangeQuery.mockImplementation(async (promql: string) => {
      const componentValues: Record<string, string> = { frontend: "0.01", orders: "0.02", payments: "0.30" };
      for (const [component, value] of Object.entries(componentValues)) {
        if (promql.includes(`"${component}"`)) {
          return [{ metric: {}, values: [[1756461600, value]] }];
        }
      }
      return [];
    });
    mockedLokiQueryRange.mockImplementation(async (logql: string) => {
      if (logql.includes('"payments"')) {
        return [{ stream: {}, values: [["1756461800000000000", "ERROR payments failure"]] }];
      }
      return [];
    });

    const result = await generateIncidentReport({ alert_id: 42 });
    const parsed = parseResult(result);
    const report: string = parsed.report;

    // error_rate is max()'d across components (agent's convention) — payments' 0.30 must win, not frontend's 0.01
    expect(report).toContain("0.3000");
    expect(report).not.toContain("| 0.0100 |");
    expect(report).toContain("payments failure");
  });

  it("does not throw when Prometheus or Loki are unreachable", async () => {
    mockedQueryOne.mockResolvedValue(makeRow());
    mockedRangeQuery.mockRejectedValue(new Error("connection refused"));
    mockedLokiQueryRange.mockRejectedValue(new Error("connection refused"));

    const result = await generateIncidentReport({ alert_id: 42 });
    const parsed = parseResult(result);

    expect(parsed.report).toContain("No metric data available");
    expect(parsed.report).toContain("No error-level logs found");
  });
});
