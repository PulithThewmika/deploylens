import { z } from "zod";
import { query } from "../clients/postgres.js";

export const getActiveAlertsSchema = {
  service: z
    .string()
    .optional()
    .describe("Filter by service name"),
  severity: z
    .enum(["warning", "critical"])
    .optional()
    .describe("Filter by severity"),
};

interface AlertRow {
  id: number;
  deployment_id: number;
  service_name: string;
  severity: string;
  title: string;
  description: string | null;
  fired_at: string;
}

async function queryActiveAlerts(
  service?: string,
  severity?: string,
): Promise<AlertRow[]> {
  const conditions: string[] = ["a.resolved_at IS NULL"];
  const params: unknown[] = [];
  let paramIdx = 1;

  if (service) {
    conditions.push(`s.name = $${paramIdx++}`);
    params.push(service);
  }
  if (severity) {
    conditions.push(`a.severity = $${paramIdx++}`);
    params.push(severity);
  }

  const where = conditions.join(" AND ");

  return query<AlertRow>(
    `SELECT
       a.id,
       a.deployment_id,
       s.name AS service_name,
       a.severity,
       a.title,
       a.description,
       a.fired_at
     FROM alerts a
     JOIN services s ON s.id = a.service_id
     WHERE ${where}
     ORDER BY a.fired_at DESC
     LIMIT 100`,
    params,
  );
}

export function buildSummary(
  alerts: AlertRow[],
  service?: string,
  severity?: string,
): string {
  if (alerts.length === 0) {
    const filters: string[] = [];
    if (service) filters.push(`service=${service}`);
    if (severity) filters.push(`severity=${severity}`);
    const suffix = filters.length > 0 ? ` (${filters.join(", ")})` : "";
    return `No active alerts${suffix}`;
  }

  const serviceCounts = new Map<string, number>();
  for (const a of alerts) {
    serviceCounts.set(a.service_name, (serviceCounts.get(a.service_name) ?? 0) + 1);
  }

  const breakdown = Array.from(serviceCounts.entries())
    .sort((a, b) => b[1] - a[1])
    .map(([svc, count]) => `${count} for ${svc}`)
    .join(", ");

  const criticalCount = alerts.filter(a => a.severity === "critical").length;
  const severityNote = criticalCount > 0
    ? ` (${criticalCount} critical)`
    : "";

  return `${alerts.length} active alert(s)${severityNote}: ${breakdown}`;
}

export async function getActiveAlerts(input: {
  service?: string;
  severity?: string;
}): Promise<{ content: { type: "text"; text: string }[] }> {
  let alerts: AlertRow[];
  try {
    alerts = await queryActiveAlerts(input.service, input.severity);
  } catch (err) {
    return {
      content: [{
        type: "text",
        text: JSON.stringify({
          error: `Database query failed: ${err instanceof Error ? err.message : String(err)}`,
          summary: `get_active_alerts failed: PostgreSQL unreachable or query error`,
        }),
      }],
    };
  }

  const summary = buildSummary(alerts, input.service, input.severity);

  return {
    content: [{
      type: "text",
      text: JSON.stringify({
        summary,
        count: alerts.length,
        alerts: alerts.map(a => ({
          id: a.id,
          deployment_id: a.deployment_id,
          service: a.service_name,
          severity: a.severity,
          title: a.title,
          description: a.description,
          fired_at: a.fired_at,
        })),
      }),
    }],
  };
}
