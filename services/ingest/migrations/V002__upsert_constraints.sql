-- V002: Partial unique indexes for webhook idempotency
-- GitHub redelivers webhooks; ArgoCD duplicates notifications.
-- These indexes enable INSERT ... ON CONFLICT ... DO UPDATE (upsert)
-- without creating duplicate deployment rows.
-- Idempotent — safe to run multiple times.

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM schema_versions WHERE version = 'V002') THEN
        RAISE NOTICE 'V002 already applied, skipping.';
        RETURN;
    END IF;

    -- GitHub webhook idempotency: one deployment per workflow_run_id.
    -- Partial index (WHERE IS NOT NULL) so rows without a workflow_run_id
    -- don't conflict with each other — ArgoCD-only orphan deployments
    -- won't have this field set.
    CREATE UNIQUE INDEX IF NOT EXISTS uq_deployments_workflow_run_id
        ON deployments (workflow_run_id)
        WHERE workflow_run_id IS NOT NULL;

    -- ArgoCD webhook idempotency: one deployment per (revision, service).
    -- Partial index (WHERE IS NOT NULL) so rows without an argocd_revision
    -- don't conflict — GitHub-only deployments that haven't synced yet
    -- won't have this field set.
    CREATE UNIQUE INDEX IF NOT EXISTS uq_deployments_argocd_revision_service
        ON deployments (argocd_revision, service_id)
        WHERE argocd_revision IS NOT NULL;

    INSERT INTO schema_versions (version, description)
    VALUES ('V002', 'Partial unique indexes on deployments for webhook upsert idempotency');

END $$;
