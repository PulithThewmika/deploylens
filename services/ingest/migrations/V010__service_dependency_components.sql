-- V010: Add component columns to service_dependencies for blast radius (E14-T3).
--
-- services.id is one row per ArgoCD app/repo (e.g. "sample-app" covers the
-- frontend/orders/payments microservices — see V005's prom_components).
-- Blast radius needs to show the chain frontend -> orders -> payments, which
-- would otherwise collapse into a self-referencing edge on the same
-- services.id since all three share one row. source_component/target_component
-- carry the finer-grained name (matches an entry in services.prom_components)
-- while source_id/target_id still point at the owning services row, so
-- existing health/DORA code that only understands the coarse granularity is
-- unaffected.
--
-- Idempotent — safe to run multiple times.

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM schema_versions WHERE version = 'V010') THEN
        RAISE NOTICE 'V010 already applied, skipping.';
        RETURN;
    END IF;

    ALTER TABLE service_dependencies
        ADD COLUMN IF NOT EXISTS source_component TEXT,
        ADD COLUMN IF NOT EXISTS target_component TEXT;

    -- Replace the old (source_id, target_id, dep_type) uniqueness with one
    -- that includes the components, so frontend->orders and orders->payments
    -- (same services.id pair in the single-app case) don't collide.
    ALTER TABLE service_dependencies
        DROP CONSTRAINT IF EXISTS service_dependencies_source_id_target_id_dep_type_key;

    CREATE UNIQUE INDEX IF NOT EXISTS service_dependencies_unique_edge
        ON service_dependencies (source_id, target_id, dep_type, source_component, target_component);

    INSERT INTO schema_versions (version, description)
    VALUES ('V010', 'Add source_component/target_component to service_dependencies for blast radius');

END $$;
