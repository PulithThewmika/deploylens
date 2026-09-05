-- V011: Update sample-app's repo mapping after EPIC-018 repo migration.
--
-- The sample app moved from the platform repo (PulithThewmika/deploylens,
-- under sample-app/) to its own repo, PulithThewmika/deploylens-sample-app.
-- V006's seed row still points `repo` at the old monorepo, so GitHub webhooks
-- from the new repo would fail to resolve_service() by repo and instead
-- auto-register a second, unlinked services row for "deploylens-sample-app" -
-- the exact split-row problem V006 exists to prevent for the CI/CD side.
--
-- Idempotent — safe to run multiple times.

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM schema_versions WHERE version = 'V011') THEN
        RAISE NOTICE 'V011 already applied, skipping.';
        RETURN;
    END IF;

    UPDATE services
       SET repo = 'PulithThewmika/deploylens-sample-app'
     WHERE name = 'sample-app';

    INSERT INTO schema_versions (version, description)
    VALUES ('V011', 'Point sample-app service repo mapping at deploylens-sample-app (EPIC-018 repo migration)');
END $$;
