-- V001: Base schema for DeployLens
-- Creates all core tables, constraints, indexes, and the grafana_ro role.
-- Idempotent — safe to run multiple times.

-- ── Schema version tracking ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS schema_versions (
    version     TEXT PRIMARY KEY,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    description TEXT
);

-- Guard: skip if this migration was already applied
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM schema_versions WHERE version = 'V001') THEN
        RAISE NOTICE 'V001 already applied, skipping.';
        RETURN;
    END IF;

    -- ── services ────────────────────────────────────────────────────────────
    CREATE TABLE IF NOT EXISTS services (
        id          SERIAL PRIMARY KEY,
        name        TEXT NOT NULL UNIQUE,
        repo        TEXT,
        argocd_app  TEXT,
        namespace   TEXT NOT NULL DEFAULT 'default',
        created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
    );

    -- ── pipeline_events ─────────────────────────────────────────────────────
    CREATE TABLE IF NOT EXISTS pipeline_events (
        id          SERIAL PRIMARY KEY,
        source      TEXT NOT NULL CHECK (source IN ('github_actions', 'argocd')),
        event_type  TEXT NOT NULL,
        payload     JSONB NOT NULL,
        received_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );

    CREATE INDEX IF NOT EXISTS idx_pipeline_events_received
        ON pipeline_events (received_at DESC);

    -- ── deployments ─────────────────────────────────────────────────────────
    CREATE TABLE IF NOT EXISTS deployments (
        id                SERIAL PRIMARY KEY,
        service_id        INTEGER NOT NULL REFERENCES services(id) ON DELETE CASCADE,
        commit_sha        TEXT,
        branch            TEXT,
        author            TEXT,
        commit_at         TIMESTAMPTZ,
        status            TEXT NOT NULL DEFAULT 'pending'
                          CHECK (status IN (
                              'pending', 'building', 'built',
                              'syncing', 'deployed',
                              'build_failed', 'sync_failed'
                          )),
        build_status      TEXT CHECK (build_status IN ('success', 'failure')),
        build_duration_s  REAL,
        sync_status       TEXT CHECK (sync_status IN ('Synced', 'OutOfSync', 'Failed', 'Unknown')),
        workflow_run_id   BIGINT,
        argocd_revision   TEXT,
        image_tag         TEXT,
        started_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
        finished_at       TIMESTAMPTZ,
        created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
    );

    CREATE INDEX IF NOT EXISTS idx_deployments_service_time
        ON deployments (service_id, started_at DESC);

    CREATE INDEX IF NOT EXISTS idx_deployments_sha
        ON deployments (commit_sha);

    CREATE INDEX IF NOT EXISTS idx_deployments_image_tag
        ON deployments (image_tag);

    -- ── health_assessments ──────────────────────────────────────────────────
    CREATE TABLE IF NOT EXISTS health_assessments (
        id                  SERIAL PRIMARY KEY,
        deployment_id       INTEGER NOT NULL UNIQUE REFERENCES deployments(id) ON DELETE CASCADE,
        score               INTEGER NOT NULL CHECK (score BETWEEN 0 AND 100),
        verdict             TEXT NOT NULL CHECK (verdict IN ('healthy', 'degraded', 'failed')),
        error_rate_base     REAL,
        error_rate_post     REAL,
        latency_p99_base_ms REAL,
        latency_p99_post_ms REAL,
        restarts_base       REAL,
        restarts_post       REAL,
        details             JSONB,
        assessed_at         TIMESTAMPTZ NOT NULL DEFAULT now()
    );

    -- ── alerts ──────────────────────────────────────────────────────────────
    CREATE TABLE IF NOT EXISTS alerts (
        id              SERIAL PRIMARY KEY,
        deployment_id   INTEGER NOT NULL REFERENCES deployments(id) ON DELETE CASCADE,
        service_id      INTEGER NOT NULL REFERENCES services(id) ON DELETE CASCADE,
        severity        TEXT NOT NULL CHECK (severity IN ('warning', 'critical')),
        title           TEXT NOT NULL,
        description     TEXT,
        fired_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
        resolved_at     TIMESTAMPTZ,
        alertmanager_id TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_alerts_active
        ON alerts (service_id, fired_at DESC)
        WHERE resolved_at IS NULL;

    -- ── safety_scores (stretch) ─────────────────────────────────────────────
    CREATE TABLE IF NOT EXISTS safety_scores (
        id              SERIAL PRIMARY KEY,
        deployment_id   INTEGER NOT NULL UNIQUE REFERENCES deployments(id) ON DELETE CASCADE,
        score           INTEGER NOT NULL CHECK (score BETWEEN 0 AND 100),
        risk_factors    JSONB,
        computed_at     TIMESTAMPTZ NOT NULL DEFAULT now()
    );

    -- ── service_dependencies (stretch) ──────────────────────────────────────
    CREATE TABLE IF NOT EXISTS service_dependencies (
        id          SERIAL PRIMARY KEY,
        source_id   INTEGER NOT NULL REFERENCES services(id) ON DELETE CASCADE,
        target_id   INTEGER NOT NULL REFERENCES services(id) ON DELETE CASCADE,
        dep_type    TEXT NOT NULL DEFAULT 'calls'
                    CHECK (dep_type IN ('calls', 'publishes', 'subscribes')),
        created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
        UNIQUE (source_id, target_id, dep_type)
    );

    -- ── grafana_ro role ─────────────────────────────────────────────────────
    -- Read-only role for Grafana PostgreSQL datasource
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'grafana_ro') THEN
        CREATE ROLE grafana_ro WITH LOGIN PASSWORD 'grafana_readonly';
    END IF;

    GRANT CONNECT ON DATABASE deploylens TO grafana_ro;
    GRANT USAGE ON SCHEMA public TO grafana_ro;
    GRANT SELECT ON ALL TABLES IN SCHEMA public TO grafana_ro;

    -- Future tables created by deploylens user are also readable
    ALTER DEFAULT PRIVILEGES FOR USER deploylens IN SCHEMA public
        GRANT SELECT ON TABLES TO grafana_ro;

    -- ── Record migration ────────────────────────────────────────────────────
    INSERT INTO schema_versions (version, description)
    VALUES ('V001', 'Base schema: services, pipeline_events, deployments, health_assessments, alerts, safety_scores, service_dependencies, grafana_ro role');

END $$;
