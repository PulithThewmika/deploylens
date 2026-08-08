-- V009: Add 'assessed' to deployments status constraint
-- The detection agent sets status='assessed' after health scoring completes.
-- Idempotent — safe to run multiple times.

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM schema_versions WHERE version = 'V009') THEN
        RAISE NOTICE 'V009 already applied, skipping.';
        RETURN;
    END IF;

    -- Drop the existing CHECK constraint and re-add with 'assessed'
    ALTER TABLE deployments
        DROP CONSTRAINT IF EXISTS deployments_status_check;

    ALTER TABLE deployments
        ADD CONSTRAINT deployments_status_check
        CHECK (status IN (
            'pending', 'building', 'built',
            'syncing', 'deployed', 'assessed',
            'build_failed', 'sync_failed'
        ));

    -- Update DORA change failure rate view to count 'degraded' verdicts
    -- per issue #37 acceptance criteria: CFR = (degraded + failed + build_failed + sync_failed) / total
    CREATE OR REPLACE VIEW dora_change_failure_rate AS
    SELECT
        s.name                              AS service_name,
        COUNT(*)                            AS total_deploys,
        COUNT(*) FILTER (
            WHERE d.status IN ('build_failed', 'sync_failed')
               OR ha.verdict IN ('failed', 'degraded')
        )                                   AS failed_deploys,
        ROUND(
            COUNT(*) FILTER (
                WHERE d.status IN ('build_failed', 'sync_failed')
                   OR ha.verdict IN ('failed', 'degraded')
            )::numeric / NULLIF(COUNT(*), 0),
            4
        )                                   AS failure_rate
    FROM deployments d
    JOIN services s ON s.id = d.service_id
    LEFT JOIN health_assessments ha ON ha.deployment_id = d.id
    WHERE d.status IN ('deployed', 'assessed', 'build_failed', 'sync_failed')
    GROUP BY s.name
    ORDER BY service_name;

    -- Re-grant read access to Grafana role
    GRANT SELECT ON dora_change_failure_rate TO grafana_ro;

    INSERT INTO schema_versions (version, description)
    VALUES ('V009', 'Add assessed status to deployments, update CFR view to count degraded verdicts');

END $$;
