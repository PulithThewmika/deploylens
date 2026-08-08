-- V005: Add prom_components column to services for Prometheus label mapping.
--
-- The agent queries Prometheus using a `service` label, but the services table
-- stores an app-level name (e.g. "sample-app") while Prometheus metrics carry
-- per-microservice labels ("frontend", "orders", "payments"). This column maps
-- a service row to its real Prometheus component labels so the agent can fan
-- out queries and aggregate results correctly. (bug #132)
--
-- Default: ARRAY[name] so existing/future services with 1:1 mapping work
-- without explicit seeding.
--
-- Idempotent — safe to run multiple times.

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM schema_versions WHERE version = 'V005') THEN
        RAISE NOTICE 'V005 already applied, skipping.';
        RETURN;
    END IF;

    ALTER TABLE services
        ADD COLUMN IF NOT EXISTS prom_components TEXT[];

    -- Backfill: default to ARRAY[name] for any service without explicit mapping
    UPDATE services
       SET prom_components = ARRAY[name]
     WHERE prom_components IS NULL;

    -- Set sample-app to its actual Prometheus component labels
    UPDATE services
       SET prom_components = ARRAY['frontend', 'orders', 'payments']
     WHERE name = 'sample-app';

    ALTER TABLE services
        ALTER COLUMN prom_components SET DEFAULT NULL;

    INSERT INTO schema_versions (version, description)
    VALUES ('V005', 'Add prom_components column for Prometheus service label mapping');

END $$;
