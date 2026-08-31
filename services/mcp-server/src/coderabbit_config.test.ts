import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const configPath = resolve(import.meta.dirname, "../../..", ".coderabbit.yaml");
const config = readFileSync(configPath, "utf8");
const lines = config.split(/\r?\n/);

function section(name: string, indent: number): string[] {
  const prefix = " ".repeat(indent);
  const start = lines.findIndex((line) => line === `${prefix}${name}:`);
  if (start === -1) return [];

  const end = lines.findIndex(
    (line, index) =>
      index > start &&
      line.trim() !== "" &&
      !line.trimStart().startsWith("#") &&
      line.length - line.trimStart().length <= indent,
  );

  return lines.slice(start + 1, end === -1 ? lines.length : end);
}

function mappingKeys(block: string[], indent: number): string[] {
  const keyPattern = new RegExp(`^ {${indent}}([A-Za-z][A-Za-z0-9_]*):`);
  return block.flatMap((line) => {
    const match = line.match(keyPattern);
    return match ? [match[1]] : [];
  });
}

function pathInstructions(): Map<string, string> {
  const entries = new Map<string, string>();
  let currentPath: string | undefined;
  let instructionLines: string[] = [];

  const saveCurrent = () => {
    if (currentPath !== undefined) {
      entries.set(currentPath, instructionLines.join(" "));
    }
  };

  for (const line of section("path_instructions", 2)) {
    const pathMatch = line.match(/^ {4}- path: "([^"]+)"$/);
    if (pathMatch) {
      saveCurrent();
      currentPath = pathMatch[1];
      instructionLines = [];
    } else if (currentPath !== undefined && /^ {8}\S/.test(line)) {
      instructionLines.push(line.trim());
    }
  }
  saveCurrent();

  return entries;
}

describe("CodeRabbit configuration", () => {
  it("uses only root keys supported by the CodeRabbit v2 schema", () => {
    // Keep this small contract in sync with
    // https://coderabbit.ai/integrations/schema.v2.json.
    const supportedRootKeys = new Set([
      "language",
      "tone_instructions",
      "early_access",
      "enable_free_tier",
      "inheritance",
      "reviews",
      "chat",
      "knowledge_base",
      "code_generation",
      "issue_enrichment",
    ]);

    const unsupportedKeys = mappingKeys(lines, 0).filter((key) => !supportedRootKeys.has(key));
    expect(unsupportedKeys).toEqual([]);
  });

  it("keeps tool integrations under reviews, where the CodeRabbit schema recognizes them", () => {
    expect(mappingKeys(section("reviews", 0), 2)).toContain("tools");
  });

  it("enables assertive automatic reviews for non-draft changes targeting dev or main", () => {
    const reviews = section("reviews", 0).join("\n");
    const autoReview = section("auto_review", 2).join("\n");

    expect(reviews).toContain("  profile: assertive");
    expect(reviews).toContain("  request_changes_workflow: false");
    expect(reviews).toContain("  high_level_summary: true");
    expect(reviews).toContain("  review_status: true");
    expect(autoReview).toContain("    enabled: true");
    expect(autoReview).toContain("    drafts: false");
    expect(autoReview.match(/^ {6}- "(dev|main)"$/gm)?.sort()).toEqual([
      '      - "dev"',
      '      - "main"',
    ]);
  });

  it("excludes generated artifacts, lockfiles, and migrations from reviews", () => {
    const filters = section("path_filters", 2)
      .flatMap((line) => line.match(/^ {4}- "([^"]+)"/)?.[1] ?? [])
      .sort();

    expect(filters).toEqual(
      ["!**/*.lock", "!**/*.min.js", "!**/migrations/**", "!**/package-lock.json", "!web/dist/**"].sort(),
    );
  });

  it("defines one instruction for every intended review surface", () => {
    expect([...pathInstructions().keys()].sort()).toEqual(
      [
        "deploy/grafana/dashboards/**/*.sql",
        "services/**/*.py",
        "services/agent/agent/health_score.py",
        "services/ingest/app/correlation/engine.py",
        "services/ingest/app/routers/webhooks_*.py",
        "services/mcp-server/**",
        "web/**",
      ].sort(),
    );
  });

  it("preserves the fixed health-score formula and guard-rail guidance", () => {
    const instructions = pathInstructions().get("services/agent/agent/health_score.py");

    expect(instructions).toContain("error_rate=45, latency_p99=30, restarts=25");
    expect(instructions).toContain(">=80 healthy, 50-79 degraded, <50 failed");
    expect(instructions).toContain("<0.1 rps in both windows");
  });

  it("preserves webhook authentication, idempotency, and correlation requirements", () => {
    const instructions = pathInstructions();
    const correlation = instructions.get("services/ingest/app/correlation/engine.py");
    const webhooks = instructions.get("services/ingest/app/routers/webhooks_*.py");

    expect(correlation).toContain("commit_sha first, image_tag fallback second");
    expect(correlation).toContain("must log at INFO");
    expect(webhooks).toContain("INSERT ... ON CONFLICT");
    expect(webhooks).toContain("X-Hub-Signature-256 HMAC");
    expect(webhooks).toContain("return 401 on mismatch");
  });

  it("keeps SQL guidance scoped away from excluded migration files", () => {
    const instructions = pathInstructions();
    const sqlPath = "deploy/grafana/dashboards/**/*.sql";

    expect(instructions.has("**/*.sql")).toBe(false);
    expect(sqlPath).not.toContain("migrations");
    expect(instructions.get(sqlPath)).toContain("read-only query");
    expect(instructions.get(sqlPath)).toContain("INSERT/UPDATE/DELETE/DDL");
    expect(instructions.get(sqlPath)).toContain("dora_mttr");
  });

  it("enables each configured analyzer, including secret scanning", () => {
    const tools = section("tools", 2);
    const toolNames = mappingKeys(tools, 4);

    expect(toolNames.sort()).toEqual(["eslint", "gitleaks", "markdownlint", "ruff", "yamllint"]);
    for (const tool of toolNames) {
      expect(section(tool, 4).some((line) => /^ {6}enabled: true(?:\s+#.*)?$/.test(line))).toBe(true);
    }
  });

  it("enables chat replies and automatic knowledge-base scopes", () => {
    expect(section("chat", 0)).toContain("  auto_reply: true");
    expect(section("learnings", 2)).toContain("    scope: auto");
    expect(section("issues", 2)).toContain("    scope: auto");
  });
});
