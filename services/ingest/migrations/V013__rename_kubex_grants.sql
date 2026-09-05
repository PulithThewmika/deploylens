-- V013: grafana_ro grants for the renamed "kubex" database/user (EPIC-025).
--
-- V001 originally granted grafana_ro access scoped to the "deploylens"
-- database/user; those grants are now guarded no-ops on this DB (see the
-- comment in V001) since the compose stack was renamed to "kubex". This
-- migration re-establishes the equivalent access, resolved dynamically via
-- current_database()/current_user rather than hardcoding "kubex" again —
-- so it doesn't need another guarded rename migration if the DB/user name
-- ever changes again.
--
-- Idempotent — safe to run multiple times.

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM schema_versions WHERE version = 'V013') THEN
        RAISE NOTICE 'V013 already applied, skipping.';
        RETURN;
    END IF;

    -- Uses current_database()/current_user (the identity this migration
    -- actually runs as) rather than hardcoding "kubex", so this doesn't
    -- silently no-op again the next time the app's DB/user name changes.
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO grafana_ro', current_database());
    GRANT USAGE ON SCHEMA public TO grafana_ro;
    GRANT SELECT ON ALL TABLES IN SCHEMA public TO grafana_ro;

    -- Future tables created by the app's DB user are also readable.
    EXECUTE format(
        'ALTER DEFAULT PRIVILEGES FOR USER %I IN SCHEMA public GRANT SELECT ON TABLES TO grafana_ro',
        current_user
    );

    INSERT INTO schema_versions (version, description)
    VALUES ('V013', 'Re-grant grafana_ro access under the renamed kubex database/user (EPIC-025)');
END $$;
