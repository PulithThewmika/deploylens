-- V008: Reshape DORA views to row-level for period filtering.
--
-- The original views (V003, updated in V004/V007) pre-aggregated metrics by
-- service_name with GROUP BY, making it impossible for consumers (API, MCP,
-- Grafana) to filter by time period. This caused the API to bypass the views
-- and use inline SQL, violating Critical Decision #6 (DORA views are the
-- single authoritative source, no duplicated logic in Python).
--
-- This migration replaces the lead_time, change_failure_rate, and mttr views
-- with row-level views that expose date columns. Consumers aggregate and
-- filter as needed. deploy_frequency already has deploy_date and is unchanged.
--
-- Idempotent — safe to run multiple times (CREATE OR REPLACE VIEW).

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM schema_versions WHERE version = 'V008') THEN
        RAISE NOTICE 'V008 already applied, skipping.';
        RETURN;
    END IF;

    -- ── Lead Time for Changes (row-level) ───────────────────────────────
    -- One row per deployment with commit_at and finished_at both set.
    -- Consumers: SELECT AVG(lead_time_seconds) ... WHERE finished_at >= ...
    CREATE OR REPLACE VIEW dora_lead_time AS
    SELECT
        s.name                              AS service_name,
        d.finished_at,
        EXTRACT(EPOCH FROM (d.finished_at - d.commit_at))
                                            AS lead_time_seconds
    FROM deployments d
    JOIN services s ON s.id = d.service_id
    WHERE d.status IN ('deployed', 'assessed')
      AND d.commit_at   IS NOT NULL
      AND d.finished_at IS NOT NULL;

    -- ── Change Failure Rate (row-level) ─────────────────────────────────
    -- One row per deployment indicating whether it was a failure.
    -- Consumers: SELECT COUNT(*) FILTER (WHERE is_failure)::numeric / COUNT(*)
    --            ... WHERE started_at >= ...
    CREATE OR REPLACE VIEW dora_change_failure_rate AS
    SELECT
        s.name                              AS service_name,
        d.started_at,
        CASE
            WHEN d.status IN ('build_failed', 'sync_failed')
              OR ha.verdict IN ('failed', 'degraded')
            THEN true
            ELSE false
        END                                 AS is_failure
    FROM deployments d
    JOIN services s ON s.id = d.service_id
    LEFT JOIN health_assessments ha ON ha.deployment_id = d.id
    WHERE d.status IN ('deployed', 'assessed', 'build_failed', 'sync_failed');

    -- ── Mean Time to Recovery (row-level) ───────────────────────────────
    -- One row per resolved alert with the recovery duration.
    -- Consumers: SELECT AVG(mttr_seconds) ... WHERE fired_at >= ...
    CREATE OR REPLACE VIEW dora_mttr AS
    SELECT
        s.name                              AS service_name,
        a.fired_at,
        EXTRACT(EPOCH FROM (a.resolved_at - a.fired_at))
                                            AS mttr_seconds
    FROM alerts a
    JOIN services s ON s.id = a.service_id
    WHERE a.resolved_at IS NOT NULL;

    -- Re-grant read access to Grafana role
    GRANT SELECT ON dora_lead_time           TO grafana_ro;
    GRANT SELECT ON dora_change_failure_rate TO grafana_ro;
    GRANT SELECT ON dora_mttr                TO grafana_ro;

    INSERT INTO schema_versions (version, description)
    VALUES ('V008', 'Reshape lead_time, change_failure_rate, mttr views to row-level for period filtering');

END $$;
