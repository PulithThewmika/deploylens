import { describe, it, expect } from "vitest";
import {
  buildPromQL,
  parseRelativeSeconds,
  resolveTimestamp,
  autoStep,
  formatResults,
  sanitizeLabel,
} from "./query_metrics.js";

describe("sanitizeLabel", () => {
  it("escapes backslash and double quotes", () => {
    expect(sanitizeLabel('foo"bar')).toBe('foo\\"bar');
    expect(sanitizeLabel("foo\\bar")).toBe("foo\\\\bar");
  });

  it("passes clean strings through", () => {
    expect(sanitizeLabel("orders")).toBe("orders");
  });
});

describe("buildPromQL", () => {
  it("builds error_rate query with service and namespace filters", () => {
    const q = buildPromQL("error_rate", "orders", "deploylens", "5m");
    expect(q).toContain('service="orders"');
    expect(q).toContain('namespace="deploylens"');
    expect(q).toContain('status=~"5.."');
    expect(q).toContain("[5m]");
    expect(q).toContain("rate(http_requests_total");
  });

  it("builds latency_p99 query with histogram_quantile", () => {
    const q = buildPromQL("latency_p99", "payments", "deploylens", "10m");
    expect(q).toContain("histogram_quantile(0.99");
    expect(q).toContain("http_request_duration_seconds_bucket");
    expect(q).toContain('service="payments"');
    expect(q).toContain("[10m]");
  });

  it("builds cpu query with container_cpu_usage_seconds_total", () => {
    const q = buildPromQL("cpu", "frontend", "deploylens", "5m");
    expect(q).toContain("container_cpu_usage_seconds_total");
    expect(q).toContain('container="frontend"');
  });

  it("builds memory query with container_memory_working_set_bytes", () => {
    const q = buildPromQL("memory", "orders", "deploylens", "5m");
    expect(q).toContain("container_memory_working_set_bytes");
    expect(q).not.toContain("[5m]");
  });

  it("builds restarts query with kube_pod_container_status_restarts_total", () => {
    const q = buildPromQL("restarts", "orders", "deploylens", "15m");
    expect(q).toContain("kube_pod_container_status_restarts_total");
    expect(q).toContain("increase(");
  });

  it("builds request_rate query", () => {
    const q = buildPromQL("request_rate", "frontend", "deploylens", "5m");
    expect(q).toContain("rate(http_requests_total");
    expect(q).not.toContain("5..");
  });
});

describe("parseRelativeSeconds", () => {
  it("parses -30m to 1800", () => {
    expect(parseRelativeSeconds("-30m")).toBe(1800);
  });

  it("parses -1h to 3600", () => {
    expect(parseRelativeSeconds("-1h")).toBe(3600);
  });

  it("parses -2d to 172800", () => {
    expect(parseRelativeSeconds("-2d")).toBe(172800);
  });

  it("parses -45s to 45", () => {
    expect(parseRelativeSeconds("-45s")).toBe(45);
  });

  it("returns null for invalid input", () => {
    expect(parseRelativeSeconds("30m")).toBeNull();
    expect(parseRelativeSeconds("now")).toBeNull();
    expect(parseRelativeSeconds("")).toBeNull();
  });
});

describe("resolveTimestamp", () => {
  const NOW = 1700000000;

  it("resolves 'now' to the current epoch", () => {
    expect(resolveTimestamp("now", NOW)).toBe(NOW.toString());
  });

  it("resolves relative time strings", () => {
    expect(resolveTimestamp("-1h", NOW)).toBe((NOW - 3600).toString());
    expect(resolveTimestamp("-30m", NOW)).toBe((NOW - 1800).toString());
  });

  it("resolves ISO8601 timestamps", () => {
    const iso = "2023-11-14T12:00:00Z";
    const expected = (Date.parse(iso) / 1000).toString();
    expect(resolveTimestamp(iso, NOW)).toBe(expected);
  });

  it("throws on unparseable input", () => {
    expect(() => resolveTimestamp("garbage", NOW)).toThrow("Cannot parse time string");
  });
});

describe("autoStep", () => {
  it("returns 15s for ranges under 1 hour", () => {
    expect(autoStep(0, 1800)).toBe("15s");
  });

  it("returns 1m for ranges 1-6 hours", () => {
    expect(autoStep(0, 7200)).toBe("1m");
  });

  it("returns 5m for ranges 6-24 hours", () => {
    expect(autoStep(0, 43200)).toBe("5m");
  });

  it("returns 15m for ranges over 24 hours", () => {
    expect(autoStep(0, 172800)).toBe("15m");
  });
});

describe("formatResults", () => {
  it("converts Prometheus range results to [{t, v}] format", () => {
    const results = [{
      metric: { service: "orders" },
      values: [
        [1700000000, "0.023"] as [number, string],
        [1700000060, "0.045"] as [number, string],
      ],
    }];
    const points = formatResults(results, "error_rate");
    expect(points).toHaveLength(2);
    expect(points[0].t).toBe(new Date(1700000000 * 1000).toISOString());
    expect(points[0].v).toBe(0.023);
    expect(points[1].v).toBe(0.045);
  });

  it("converts latency_p99 from seconds to milliseconds", () => {
    const results = [{
      metric: {},
      values: [[1700000000, "0.150"] as [number, string]],
    }];
    const points = formatResults(results, "latency_p99");
    expect(points[0].v).toBe(150);
  });

  it("returns empty array for empty results", () => {
    expect(formatResults([], "error_rate")).toEqual([]);
  });

  it("converts NaN values to 0", () => {
    const results = [{
      metric: {},
      values: [[1700000000, "NaN"] as [number, string]],
    }];
    const points = formatResults(results, "restarts");
    expect(points[0].v).toBe(0);
  });
});
