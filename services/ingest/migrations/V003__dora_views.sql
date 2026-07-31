-- V003: DORA metric SQL views
-- Four views providing the single authoritative source for DORA metrics.
-- Read by REST API, MCP server, and Grafana — no duplicated logic in Python.
-- Idempotent — safe to run multiple times.

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM schema_versions WHERE version = 'V003') THEN
        RAISE NOTICE 'V003 already applied, skipping.';
        RETURN;
    END IF;

    -- ── Deploy Frequency ────────────────────────────────────────────────
    -- How often does the team deploy to production?
    -- Groups successful deployments by date and service.
    CREATE OR REPLACE VIEW dora_deploy_frequency AS
    SELECT
        d.finished_at::date                 AS deploy_date,
        s.name                              AS service_name,
        COUNT(*)                            AS deploy_count
    FROM deployments d
    JOIN services s ON s.id = d.service_id
    WHERE d.status = 'deployed'
      AND d.finished_at IS NOT NULL
    GROUP BY d.finished_at::date, s.name
    ORDER BY deploy_date DESC, service_name;

    -- ── Lead Time for Changes ───────────────────────────────────────────
    -- How long from commit to production?
    -- Average seconds between commit_at (when code was authored) and
    -- finished_at (when ArgoCD finished deploying).
    CREATE OR REPLACE VIEW dora_lead_time AS
    SELECT
        s.name                              AS service_name,
        AVG(
            EXTRACT(EPOCH FROM (d.finished_at - d.commit_at))
        )                                   AS avg_lead_time_seconds
    FROM deployments d
    JOIN services s ON s.id = d.service_id
    WHERE d.status = 'deployed'
      AND d.commit_at   IS NOT NULL
      AND d.finished_at IS NOT NULL
    GROUP BY s.name
    ORDER BY service_name;

    -- ── Change Failure Rate ─────────────────────────────────────────────
    -- What percentage of deployments cause a failure?
    -- A deployment is "failed" if it never reached 'deployed' status
    -- (build_failed, sync_failed) OR if its health assessment verdict
    -- was 'failed'.
    CREATE OR REPLACE VIEW dora_change_failure_rate AS
    SELECT
        s.name                              AS service_name,
        COUNT(*)                            AS total_deploys,
        COUNT(*) FILTER (
            WHERE d.status IN ('build_failed', 'sync_failed')
               OR ha.verdict = 'failed'
        )                                   AS failed_deploys,
        ROUND(
            COUNT(*) FILTER (
                WHERE d.status IN ('build_failed', 'sync_failed')
                   OR ha.verdict = 'failed'
            )::numeric / NULLIF(COUNT(*), 0),
            4
        )                                   AS failure_rate
    FROM deployments d
    JOIN services s ON s.id = d.service_id
    LEFT JOIN health_assessments ha ON ha.deployment_id = d.id
    WHERE d.status IN ('deployed', 'build_failed', 'sync_failed')
    GROUP BY s.name
    ORDER BY service_name;

    -- ── Mean Time to Recovery ───────────────────────────────────────────
    -- How long does it take to recover from a failure?
    -- Average seconds between alert fired_at and resolved_at for
    -- resolved alerts, grouped by service.
    CREATE OR REPLACE VIEW dora_mttr AS
    SELECT
        s.name                              AS service_name,
        AVG(
            EXTRACT(EPOCH FROM (a.resolved_at - a.fired_at))
        )                                   AS avg_mttr_seconds
    FROM alerts a
    JOIN services s ON s.id = a.service_id
    WHERE a.resolved_at IS NOT NULL
    GROUP BY s.name
    ORDER BY service_name;

    -- ── Grant read access to Grafana role ───────────────────────────────
    GRANT SELECT ON dora_deploy_frequency     TO grafana_ro;
    GRANT SELECT ON dora_lead_time            TO grafana_ro;
    GRANT SELECT ON dora_change_failure_rate  TO grafana_ro;
    GRANT SELECT ON dora_mttr                 TO grafana_ro;

    -- ── Record migration ────────────────────────────────────────────────
    INSERT INTO schema_versions (version, description)
    VALUES ('V003', 'DORA metric SQL views: deploy_frequency, lead_time, change_failure_rate, mttr');

END $$;
