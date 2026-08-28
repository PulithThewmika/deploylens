import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

import * as postgres from "./clients/postgres.js";
import * as prometheus from "./clients/prometheus.js";
import * as loki from "./clients/loki.js";
import {
  listDeploymentsSchema,
  listDeployments,
} from "./tools/list_deployments.js";
import {
  getDeploymentSchema,
  getDeployment,
} from "./tools/get_deployment.js";
import {
  getDeployHealthSchema,
  getDeployHealth,
} from "./tools/get_deploy_health.js";
import {
  compareDeploysSchema,
  compareDeploys,
} from "./tools/compare_deploys.js";
import {
  queryMetricsSchema,
  queryMetrics,
} from "./tools/query_metrics.js";
import {
  queryLogsSchema,
  queryLogs,
} from "./tools/query_logs.js";
import {
  getDoraMetricsSchema,
  getDoraMetrics,
} from "./tools/get_dora_metrics.js";
import {
  getActiveAlertsSchema,
  getActiveAlerts,
} from "./tools/get_active_alerts.js";

const server = new McpServer({
  name: "deploylens",
  version: "0.1.0",
});

// ── Tool: list_deployments ──────────────────────────────────────
server.tool(
  "list_deployments",
  "List recent deployments, optionally filtered by service name or status. Returns a summary highlighting any unhealthy deploys.",
  listDeploymentsSchema,
  async (input) => listDeployments(input),
);

// ── Tool: get_deployment ────────────────────────────────────────
server.tool(
  "get_deployment",
  "Get full details of a specific deployment by ID, including service info, pipeline timeline, and health assessment",
  getDeploymentSchema,
  async (input) => getDeployment(input),
);

// ── Tool: get_deploy_health ─────────────────────────────────────
server.tool(
  "get_deploy_health",
  "Get the health assessment for a deployment with score breakdown and metric evidence (error rate, latency, restarts)",
  getDeployHealthSchema,
  async (input) => getDeployHealth(input),
);

// ── Tool: compare_deploys ───────────────────────────────────────
server.tool(
  "compare_deploys",
  "Compare two deployments side by side — status, health score, and live Prometheus metrics (error rate, p99 latency, restarts) with change percentages",
  compareDeploysSchema,
  async (input) => compareDeploys(input),
);

// ── Tool: query_metrics ─────────────────────────────────────────
server.tool(
  "query_metrics",
  "Query Prometheus metrics for a service by intent (metric enum), not raw PromQL. Returns time series, unit, the actual PromQL executed, and a human-readable summary.",
  queryMetricsSchema,
  async (input) => queryMetrics(input),
);

// ── Tool: query_logs ────────────────────────────────────────────
server.tool(
  "query_logs",
  "Query application logs from Loki by service name with optional keyword and log-level filters. Returns timestamped log lines, the LogQL query executed, and a summary with level breakdown.",
  queryLogsSchema,
  async (input) => queryLogs(input),
);

// ── Tool: get_dora_metrics ──────────────────────────────────────
server.tool(
  "get_dora_metrics",
  "Get DORA metrics (deploy frequency, lead time, change failure rate, MTTR) aggregated over a configurable period. Reads from the authoritative SQL views.",
  getDoraMetricsSchema,
  async (input) => getDoraMetrics(input),
);

// ── Tool: get_active_alerts ─────────────────────────────────────
server.tool(
  "get_active_alerts",
  "Get currently active (unresolved) alerts with deployment linkage, optionally filtered by service or severity.",
  getActiveAlertsSchema,
  async (input) => getActiveAlerts(input),
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
