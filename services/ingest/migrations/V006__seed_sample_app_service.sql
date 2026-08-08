-- V006: Seed the sample-app service with its repo <-> argocd_app mapping.
--
-- Correlation requires CI events (GitHub webhooks, keyed by `repo`) and CD
-- events (ArgoCD notifications, keyed by `argocd_app`) to resolve to the SAME
-- services row. Auto-registration alone cannot link them: the GitHub repo's
-- last path segment ("deploylens") differs from the ArgoCD application name
-- ("sample-app"), so resolve_service() would create two separate rows and a
-- build would never correlate with its deployment (bug #112).
--
-- Seeding the mapping explicitly makes resolve_service() return one service for
-- both webhook sources — it matches by `repo` for GitHub and by `argocd_app`
-- for ArgoCD, both landing on this row.
--
-- Model note: a deployment record represents an app-level release of the
-- sample-app (one GitHub repo, one ArgoCD app). Per-microservice health
-- (frontend/orders/payments) is distinguished at query time via the `service`
-- Prometheus label, not by separate deployment rows.
--
-- Idempotent — safe to run multiple times.

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM schema_versions WHERE version = 'V006') THEN
        RAISE NOTICE 'V006 already applied, skipping.';
        RETURN;
    END IF;

    -- Upsert on the unique service name so a previously auto-registered
    -- CD-only row (argocd_app set, repo NULL) gets its repo linked.
    INSERT INTO services (name, repo, argocd_app, namespace)
    VALUES ('sample-app', 'PulithThewmika/deploylens', 'sample-app', 'deploylens')
    ON CONFLICT (name) DO UPDATE
        SET repo       = EXCLUDED.repo,
            argocd_app = EXCLUDED.argocd_app,
            namespace  = EXCLUDED.namespace;

    INSERT INTO schema_versions (version, description)
    VALUES ('V006', 'Seed sample-app service with repo <-> argocd_app mapping for CI/CD correlation');
END $$;
