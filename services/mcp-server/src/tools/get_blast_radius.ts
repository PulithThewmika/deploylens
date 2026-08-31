import { z } from "zod";
import { query, queryOne } from "../clients/postgres.js";

export const getBlastRadiusSchema = {
  service: z
    .string()
    .describe(
      "Service or component name — either a services.name (e.g. 'sample-app') or one of its " +
        "prom_components entries (e.g. 'orders'). A services.name expands to the blast radius " +
        "of all of that service's components combined.",
    ),
};

interface MatchedServiceRow {
  id: number;
  name: string;
  prom_components: string[] | null;
}

interface EdgeRow {
  source_component: string;
  target_component: string;
  dep_type: string;
  target_service_id: number;
  target_service_name: string;
}

interface HealthRow {
  verdict: string | null;
  score: number | null;
  assessed_at: Date | null;
}

export async function getBlastRadius(input: {
  service: string;
}): Promise<{ content: { type: "text"; text: string }[] }> {
  const matched = await queryOne<MatchedServiceRow>(
    `SELECT id, name, prom_components FROM services
     WHERE name = $1 OR $1 = ANY(prom_components)
     LIMIT 1`,
    [input.service],
  );

  if (!matched) {
    return {
      content: [
        {
          type: "text",
          text: JSON.stringify({
            error: `No service or component named '${input.service}' found`,
            summary: `get_blast_radius failed: '${input.service}' not found`,
          }),
        },
      ],
    };
  }

  // A component name scopes to just that component; a services.name expands
  // to every component that service owns (blast radius doesn't track
  // per-component health separately — see V010 migration notes).
  const sourceComponents =
    matched.name === input.service ? matched.prom_components ?? [] : [input.service];

  if (sourceComponents.length === 0) {
    return {
      content: [
        {
          type: "text",
          text: JSON.stringify({
            summary: `${matched.name} has no known components (prom_components not set) — blast radius unavailable`,
            service: matched.name,
            downstream: [],
          }),
        },
      ],
    };
  }

  const edges = await query<EdgeRow>(
    `SELECT sd.source_component, sd.target_component, sd.dep_type,
            s2.id AS target_service_id, s2.name AS target_service_name
     FROM service_dependencies sd
     JOIN services s2 ON s2.id = sd.target_id
     WHERE sd.source_id = $1 AND sd.source_component = ANY($2::text[])
     ORDER BY sd.source_component, sd.target_component`,
    [matched.id, sourceComponents],
  );

  const downstream = await Promise.all(
    edges.map(async (edge) => {
      const health = await queryOne<HealthRow>(
        `SELECT ha.verdict, ha.score, ha.assessed_at
         FROM health_assessments ha
         JOIN deployments d ON d.id = ha.deployment_id
         WHERE d.service_id = $1
         ORDER BY ha.assessed_at DESC
         LIMIT 1`,
        [edge.target_service_id],
      );
      return {
        source_component: edge.source_component,
        target_component: edge.target_component,
        dep_type: edge.dep_type,
        target_service: edge.target_service_name,
        // Health is tracked per services row (the owning ArgoCD app), not
        // per component — this is the target component's parent service's
        // most recent deployment health, which all of that service's
        // components share.
        current_health: health
          ? { verdict: health.verdict, score: health.score, assessed_at: health.assessed_at }
          : null,
      };
    }),
  );

  const atRiskCount = downstream.filter(
    (d) => d.current_health?.verdict && d.current_health.verdict !== "healthy",
  ).length;

  const summary =
    downstream.length === 0
      ? `${input.service} has no discovered downstream dependencies`
      : `${input.service} blast radius: ${downstream.length} downstream component(s)` +
        (atRiskCount > 0 ? `, ${atRiskCount} not currently healthy` : "");

  return {
    content: [
      {
        type: "text",
        text: JSON.stringify({
          summary,
          service: matched.name,
          queried_components: sourceComponents,
          downstream,
        }),
      },
    ],
  };
}
