-- V013: grafana_ro grants for the renamed "kubex" database/user (EPIC-025).
--
-- V001 originally granted grafana_ro access scoped to the "deploylens"
-- database/user; those grants are now guarded no-ops on this DB (see the
-- comment in V001) since the compose stack was renamed to "kubex". This
-- migration re-establishes the equivalent access under the new names.
--
-- Idempotent — safe to run multiple times.

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM schema_versions WHERE version = 'V013') THEN
        RAISE NOTICE 'V013 already applied, skipping.';
        RETURN;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_database WHERE datname = 'kubex') THEN
        GRANT CONNECT ON DATABASE kubex TO grafana_ro;
    END IF;
    GRANT USAGE ON SCHEMA public TO grafana_ro;
    GRANT SELECT ON ALL TABLES IN SCHEMA public TO grafana_ro;

    -- Future tables created by the kubex user are also readable.
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kubex') THEN
        ALTER DEFAULT PRIVILEGES FOR USER kubex IN SCHEMA public
            GRANT SELECT ON TABLES TO grafana_ro;
    END IF;

    INSERT INTO schema_versions (version, description)
    VALUES ('V013', 'Re-grant grafana_ro access under the renamed kubex database/user (EPIC-025)');
END $$;
