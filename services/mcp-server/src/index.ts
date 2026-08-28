import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

import * as postgres from "./clients/postgres.js";
import * as prometheus from "./clients/prometheus.js";
import * as loki from "./clients/loki.js";

const server = new McpServer({
  name: "deploylens",
  version: "0.1.0",
});

// ── Tool: list_deployments ──────────────────────────────────────
server.tool(
  "list_deployments",
  "List recent deployments, optionally filtered by service name or status",
  {
    service: z.string().optional().describe("Filter by service name"),
    status: z.string().optional().describe("Filter by deployment status"),
    limit: z.number().int().min(1).max(100).default(20).describe("Max results"),
  },
  async () => ({ content: [{ type: "text", text: "TODO: implement" }] }),
);

// ── Tool: get_deployment ────────────────────────────────────────
server.tool(
  "get_deployment",
  "Get full details of a specific deployment by ID",
  {
    deployment_id: z.number().int().describe("Deployment ID"),
  },
  async () => ({ content: [{ type: "text", text: "TODO: implement" }] }),
);

// ── Tool: get_deploy_health ─────────────────────────────────────
server.tool(
  "get_deploy_health",
  "Get the health assessment for a deployment, including score breakdown",
  {
    deployment_id: z.number().int().describe("Deployment ID"),
  },
  async () => ({ content: [{ type: "text", text: "TODO: implement" }] }),
);

// ── Tool: compare_deploys ───────────────────────────────────────
server.tool(
  "compare_deploys",
  "Compare two deployments side by side — status, health score, and metrics",
  {
    deployment_id_a: z.number().int().describe("First deployment ID"),
    deployment_id_b: z.number().int().describe("Second deployment ID"),
  },
  async () => ({ content: [{ type: "text", text: "TODO: implement" }] }),
);

// ── Tool: query_metrics ─────────────────────────────────────────
server.tool(
  "query_metrics",
  "Run a PromQL query against Prometheus and return results",
  {
    query: z.string().describe("PromQL expression"),
    start: z.string().optional().describe("Range start (RFC3339 or relative like '1h')"),
    end: z.string().optional().describe("Range end (RFC3339 or 'now')"),
    step: z.string().optional().describe("Step interval (e.g. '15s', '1m')"),
  },
  async () => ({ content: [{ type: "text", text: "TODO: implement" }] }),
);

// ── Tool: query_logs ────────────────────────────────────────────
server.tool(
  "query_logs",
  "Query application logs from Loki using LogQL",
  {
    query: z.string().describe("LogQL expression"),
    start: z.string().describe("Start time (RFC3339 or relative)"),
    end: z.string().optional().describe("End time (RFC3339 or 'now')"),
    limit: z.number().int().min(1).max(5000).default(500).describe("Max log lines"),
  },
  async () => ({ content: [{ type: "text", text: "TODO: implement" }] }),
);

// ── Tool: get_dora_metrics ──────────────────────────────────────
server.tool(
  "get_dora_metrics",
  "Get DORA metrics (deploy frequency, lead time, change failure rate, MTTR)",
  {
    service: z.string().optional().describe("Filter by service name"),
    period: z.enum(["24h", "7d", "30d", "90d"]).default("30d").describe("Time period"),
  },
  async () => ({ content: [{ type: "text", text: "TODO: implement" }] }),
);

// ── Tool: get_active_alerts ─────────────────────────────────────
server.tool(
  "get_active_alerts",
  "Get currently active alerts from the alerts table",
  {
    service: z.string().optional().describe("Filter by service name"),
    severity: z.string().optional().describe("Filter by severity"),
  },
  async () => ({ content: [{ type: "text", text: "TODO: implement" }] }),
);

const TOOL_COUNT = 8;

async function main(): Promise<void> {
  await postgres.testConnection();
  await prometheus.testConnection();
  await loki.testConnection();

  console.log(`MCP server ready, ${TOOL_COUNT} tools registered`);

  const transport = new StdioServerTransport();
  await server.connect(transport);
}

main().catch((err) => {
  console.error("Fatal:", err);
  process.exit(1);
});
