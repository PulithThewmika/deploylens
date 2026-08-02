-- Reusable deployment-annotation query for Grafana time-series panels.
-- Runs against the PostgreSQL datasource as grafana_ro.
--
-- Grafana annotation queries must project the following columns:
--   time  -> annotation timestamp (deployment.finished_at)
--   title -> short label shown on hover           ("Deploy #52 (9f3ab21)")
--   text  -> longer description                    ("frontend | verdict=healthy score=94")
--   tags  -> comma-separated tags Grafana can color-map (verdict + service)
--
-- Uses the $service template variable (single-select). Pass '*' to match all services.
-- The $__timeFilter macro is required so Grafana narrows the query to the panel's time range.
--
-- Verdict → color mapping is applied in the dashboard's annotation settings:
--   healthy  -> green
--   degraded -> orange
--   failed   -> red
-- Deployments without a health assessment yet get tag 'pending' (grey by default).

SELECT
    d.finished_at                                       AS time,
    'Deploy #' || d.id || ' (' || substring(d.commit_sha, 1, 7) || ')' AS title,
    s.name || ' | verdict=' || COALESCE(ha.verdict, 'pending')
           || COALESCE(' score=' || ha.score::text, '')  AS text,
    COALESCE(ha.verdict, 'pending') || ',' || s.name    AS tags
FROM deployments d
JOIN services s ON s.id = d.service_id
LEFT JOIN health_assessments ha ON ha.deployment_id = d.id
WHERE d.finished_at IS NOT NULL
  AND d.status = 'deployed'
  AND ('$service' = '*' OR s.name = '$service')
  AND $__timeFilter(d.finished_at)
ORDER BY d.finished_at DESC;
