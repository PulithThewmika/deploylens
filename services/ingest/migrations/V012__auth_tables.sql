-- V012: Auth tables for DeployLens SaaS transition (EPIC-019).
--
-- organizations, users, org_memberships, api_keys — the identity layer
-- Phase 2 (OAuth) and Phase 3 (multi-tenancy) build on. UUID primary keys
-- throughout since these rows are referenced by external tokens (JWTs,
-- API keys) that should not leak sequential integer IDs.
--
-- Idempotent — safe to run multiple times.

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM schema_versions WHERE version = 'V012') THEN
        RAISE NOTICE 'V012 already applied, skipping.';
        RETURN;
    END IF;

    -- ── organizations ───────────────────────────────────────────────────────
    -- github_org_id is NULL for personal accounts (no GitHub org) — an
    -- auto-created org backing a single user. UNIQUE allows multiple NULLs,
    -- so many personal-account orgs can coexist.
    CREATE TABLE IF NOT EXISTS organizations (
        id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        github_org_id  BIGINT UNIQUE,
        name           TEXT NOT NULL,
        slug           TEXT NOT NULL UNIQUE,
        created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
    );

    -- ── users ───────────────────────────────────────────────────────────────
    -- One row per GitHub identity; email nullable since GitHub accounts can
    -- have no public/verified email even with the user:email scope granted.
    CREATE TABLE IF NOT EXISTS users (
        id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        github_id   BIGINT NOT NULL UNIQUE,
        login       TEXT NOT NULL,
        email       TEXT,
        avatar_url  TEXT,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
    );

    -- ── org_memberships ─────────────────────────────────────────────────────
    -- Composite PK: a user belongs to an org at most once. First user for an
    -- org is 'owner', subsequent joins are 'member' (enforced in app code,
    -- not here).
    CREATE TABLE IF NOT EXISTS org_memberships (
        user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        org_id     UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
        role       TEXT NOT NULL CHECK (role IN ('owner', 'member')),
        joined_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (user_id, org_id)
    );

    INSERT INTO schema_versions (version, description)
    VALUES ('V012', 'Auth tables: organizations, users, org_memberships, api_keys');
END $$;
