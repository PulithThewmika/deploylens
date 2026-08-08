-- V007: Fix dora_deploy_frequency and dora_lead_time to include assessed deployments.
--
-- V004__assessed_status.sql introduced the 'assessed' deployment status and
-- updated dora_change_failure_rate to accept it, but left deploy_frequency
-- and lead_time filtering on status = 'deployed' only. Since the detection
-- agent transitions deployments from 'deployed' to 'assessed' after health
-- scoring, every scored deployment drops out of both views — making deploy
-- frequency and lead time decay toward zero as the agent processes the
-- backlog. (bug #134)
--
-- Idempotent — safe to run multiple times (CREATE OR REPLACE VIEW).

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM schema_versions WHERE version = 'V007') THEN
        RAISE NOTICE 'V007 already applied, skipping.';
        RETURN;
    END IF;

    -- ── Deploy Frequency ────────────────────────────────────────────────
    CREATE OR REPLACE VIEW dora_deploy_frequency AS
    SELECT
        d.finished_at::date                 AS deploy_date,
        s.name                              AS service_name,
        COUNT(*)                            AS deploy_count
    FROM deployments d
    JOIN services s ON s.id = d.service_id
    WHERE d.status IN ('deployed', 'assessed')
      AND d.finished_at IS NOT NULL
    GROUP BY d.finished_at::date, s.name
    ORDER BY deploy_date DESC, service_name;

    -- ── Lead Time for Changes ───────────────────────────────────────────
    CREATE OR REPLACE VIEW dora_lead_time AS
    SELECT
        s.name                              AS service_name,
        AVG(
            EXTRACT(EPOCH FROM (d.finished_at - d.commit_at))
        )                                   AS avg_lead_time_seconds
    FROM deployments d
    JOIN services s ON s.id = d.service_id
    WHERE d.status IN ('deployed', 'assessed')
      AND d.commit_at   IS NOT NULL
      AND d.finished_at IS NOT NULL
    GROUP BY s.name
    ORDER BY service_name;

    -- Re-grant read access to Grafana role
    GRANT SELECT ON dora_deploy_frequency TO grafana_ro;
    GRANT SELECT ON dora_lead_time        TO grafana_ro;

    INSERT INTO schema_versions (version, description)
    VALUES ('V007', 'Fix deploy_frequency and lead_time views to include assessed deployments');

END $$;
