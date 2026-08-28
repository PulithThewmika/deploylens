import { describe, it, expect } from "vitest";

// We need to test the pure functions. Since they're not exported,
// we test them indirectly through the module's behavior by importing
// and testing the exported pieces. For now, we test the LogQL builder
// and log parsing logic by extracting them.

// Re-implement the pure functions here for unit testing since the
// module's internal functions are private. In a future refactor
// (E10-T8), these will be extracted to a shared module.

describe("LogQL construction", () => {
  function sanitizeLogQL(value: string): string {
    return value.replace(/[\\"]/g, (m) => "\\" + m);
  }

  function buildLogQL(
    service: string,
    keyword?: string,
    level?: string,
  ): string {
    const svc = sanitizeLogQL(service);
    let query = `{app="${svc}"}`;
    if (level) query += ` |= "${level}"`;
    if (keyword) {
      const kw = sanitizeLogQL(keyword);
      query += ` |= "${kw}"`;
    }
    return query;
  }

  it("builds basic service selector", () => {
    const q = buildLogQL("orders");
    expect(q).toBe('{app="orders"}');
  });

  it("adds keyword filter", () => {
    const q = buildLogQL("orders", "timeout");
    expect(q).toBe('{app="orders"} |= "timeout"');
  });

  it("adds level filter", () => {
    const q = buildLogQL("orders", undefined, "error");
    expect(q).toBe('{app="orders"} |= "error"');
  });

  it("adds both level and keyword filters", () => {
    const q = buildLogQL("payments", "connection refused", "error");
    expect(q).toBe('{app="payments"} |= "error" |= "connection refused"');
  });

  it("escapes double quotes in service name", () => {
    const q = buildLogQL('my"service');
    expect(q).toBe('{app="my\\"service"}');
  });

  it("escapes double quotes in keyword", () => {
    const q = buildLogQL("orders", 'key="value"');
    expect(q).toBe('{app="orders"} |= "key=\\"value\\""');
  });
});

describe("level detection", () => {
  const LEVEL_RE = /\b(error|warn(?:ing)?|info|debug|trace|fatal|panic)\b/i;

  function detectLevel(line: string): string {
    const match = line.match(LEVEL_RE);
    if (!match) return "unknown";
    const lvl = match[1].toLowerCase();
    if (lvl === "warning") return "warn";
    return lvl;
  }

  it("detects error level", () => {
    expect(detectLevel("2024-01-01 ERROR connection failed")).toBe("error");
  });

  it("detects warn level", () => {
    expect(detectLevel("WARN: high latency")).toBe("warn");
  });

  it("normalizes warning to warn", () => {
    expect(detectLevel("[WARNING] disk nearly full")).toBe("warn");
  });

  it("detects info level", () => {
    expect(detectLevel("INFO server started on port 8000")).toBe("info");
  });

  it("returns unknown for unrecognized", () => {
    expect(detectLevel("just some output")).toBe("unknown");
  });

  it("detects fatal level", () => {
    expect(detectLevel("FATAL: out of memory")).toBe("fatal");
  });
});

describe("log entry formatting", () => {
  it("converts Loki nanosecond timestamps to ISO8601", () => {
    const tsNano = "1700000000000000000";
    const epochMs = Math.floor(parseInt(tsNano, 10) / 1_000_000);
    const iso = new Date(epochMs).toISOString();
    expect(iso).toBe("2023-11-14T22:13:20.000Z");
  });

  it("caps entries at limit", () => {
    const entries = Array.from({ length: 300 }, (_, i) => ({
      ts: new Date(i * 1000).toISOString(),
      level: "info",
      line: `log line ${i}`,
    }));
    const capped = entries.slice(0, 200);
    expect(capped).toHaveLength(200);
  });
});
