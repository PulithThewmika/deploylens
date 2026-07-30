# CLAUDE.md — DeployLens

## What This Project Is

DeployLens is a **deployment-aware observability platform**. It correlates GitHub Actions (CI), ArgoCD (CD), and Kubernetes runtime health into unified per-deployment records, autonomously scores every release's health, computes DORA metrics, and exposes the full surface through an MCP server for natural-language incident investigation.

The novel core is the **correlation engine**: linking CI events and CD events into one deployment record, and the **health scoring agent**: automatically answering "did this deployment make things worse?"

This is a solo academic project (12-week timeline, viva defense at the end). Explainability and exact adherence to the spec docs matter — deviations from documented formulas break the defense story.

## Architecture Overview

```
GitHub Actions ──webhook──▶ ┌─────────────────┐
ArgoCD Notifications ──────▶ │  Ingest Service │──▶ PostgreSQL 16 ◀── Detection Agent ──▶ Prometheus
                             │  (FastAPI)      │        ▲                    │
                             └─────────────────┘        │                    ▼
                                                        │              Alertmanager ──▶ Slack
             MCP Server ◀───────────────────────────────┤
             React Shell ◀── REST API (ingest svc) ─────┤
             Grafana (embedded panels + dashboards) ────┘
```

**Two runtime zones:**
- **Kind cluster** (`deploylens`): sample app (frontend → orders → payments), Prometheus stack, Loki + Fluent-Bit, ArgoCD, Alertmanager — all in-cluster.
- **docker-compose** (central platform): PostgreSQL 16, ingest service, Grafana, detection agent. Runs outside the cluster for fast iteration.

**PostgreSQL is the integration contract** — every producer (ingest, agent) writes to it; every consumer (MCP server, Grafana, REST API) reads from it.

## Planned Repository Layout

```
deploy/
  kind-config.yaml            # Kind cluster with extraPortMappings (30080→8080)
  docker-compose.yml          # postgres, ingest, grafana (+ agent later)
  helm-values/                # kube-prometheus-stack, loki, fluent-bit values
  argocd/                     # ArgoCD app CRDs + notifications config
  grafana/
    datasources/datasources.yml
    dashboards/               # provisioned dashboard JSON + provider.yml
services/
  ingest/                     # FastAPI: webhooks, REST API, chat proxy
    app/main.py
    app/routers/              # webhooks_github, webhooks_argocd, api, chat
    app/models/               # SQLAlchemy 2.x models
    app/schemas/              # Pydantic v2 response schemas
    app/correlation/engine.py # THE novel core — correlation logic
    app/auth.py               # HMAC + bearer token verification
    migrations/               # versioned SQL (V001, V002, ...)
  agent/                      # Detection agent (no HTTP API, pure batch loop)
    agent/run.py              # APScheduler 60s loop
    agent/health_score.py     # scoring formula (doc 05 — exact)
    agent/promql.py           # PromQL query builders
    agent/alerting.py         # Alertmanager client
  mcp/                        # MCP server (M3)
sample-app/
  frontend/  orders/  payments/   # FastAPI microservices with chaos flags
  deploy/                     # K8s manifests + ServiceMonitors + loadgen
shell/                        # React unified shell (M3)
.github/workflows/sample-app.yml
Makefile
.env                          # NEVER commit — all credentials live here
.env.example                  # committed, redacted
```

## Tech Stack

| Layer | Choice |
|---|---|
| Backend services | Python, FastAPI, SQLAlchemy 2.x (`mapped_column` syntax), Pydantic v2, asyncpg (async everywhere) |
| Database | PostgreSQL 16; versioned SQL migrations; `grafana_ro` read-only role |
| Metrics | Prometheus (kube-prometheus-stack Helm chart, Grafana disabled) |
| Logs | Loki (single-binary, auth off) + Fluent-Bit DaemonSet |
| CD | ArgoCD + Notifications controller (webhook delivery to ingest) |
| Scheduling | APScheduler (dev) / K8s CronJob (prod) for the agent |
| Frontend | React shell (Vite, dev origin `http://localhost:5173`) |
| Dashboards | Grafana, provisioned via YAML, `GF_SECURITY_ALLOW_EMBEDDING=true` |
| AI interface | MCP server exposing deployment/metrics/logs tools |

## Critical Architectural Decisions (do not violate)

1. **image_tag correlation fallback** — When GitHub Actions commits an image-tag bump to the manifests, ArgoCD's sync revision SHA ≠ the original commit SHA. Primary correlation is `commit_sha`; fallback is `image_tag`. This was the #1 identified architectural blocker. The `deployments.image_tag` column exists solely for this.

2. **`service` label on all metrics** — Every Prometheus metric from the sample app and ingest MUST carry a `service` label (via `prometheus-fastapi-instrumentator` config). Every PromQL query in the agent and MCP server filters on it. Without it, health scoring silently returns no data.

3. **Webhook idempotency via partial unique indexes** — GitHub redelivers webhooks; ArgoCD duplicates notifications. All webhook writes are `INSERT ... ON CONFLICT ... DO UPDATE` against partial unique indexes: `deployments(workflow_run_id) WHERE workflow_run_id IS NOT NULL` and `deployments(argocd_revision, service_id) WHERE argocd_revision IS NOT NULL`.

4. **Health score formula is fixed** (doc 05 — implement exactly):
   - Penalties (each clamped 0–1): error_rate `clamp((post-base)/0.05, 0, 1)`; latency_p99 `clamp((post/base - 1.2)/1.8, 0, 1)`; restarts `clamp((post-base)/3.0, 0, 1)`
   - Weights: error_rate **45**, latency_p99 **30**, restarts **25**
   - `score = clamp(100 - Σ(weight × penalty), 0, 100)`, rounded to int
   - Verdict: ≥80 healthy, 50–79 degraded, <50 failed
   - Guard rail: if request volume < 0.1 rps in both windows, skip error/latency penalties and note it in `details` JSONB
   - Windows: `BASELINE_WINDOW=30m`, `OBSERVATION_WINDOW=15m` (env-configurable)

5. **Deployment lifecycle states**: `pending → building → built → syncing → deployed`, with failure branches `build_failed` and `sync_failed`. GitHub webhook drives building/built; ArgoCD webhook drives syncing/deployed.

6. **DORA metrics are SQL views** (`dora_deploy_frequency`, `dora_lead_time`, `dora_change_failure_rate`, `dora_mttr`) — single authoritative place, read by API, MCP, and Grafana. No duplicated logic in Python.

7. **Auto-registration** — unknown services arriving via webhook get a row in `services` automatically (resolved via `repo` for GitHub, `argocd_app` for ArgoCD).

8. **Orphan events** — an ArgoCD event arriving before its CI event creates a deployment with `status='syncing'`; the GitHub event later merges into it via correlation.

## Security Baseline

- GitHub webhooks: HMAC verification via `X-Hub-Signature-256` against `GITHUB_WEBHOOK_SECRET`; 401 on mismatch.
- ArgoCD webhooks: shared bearer token (`ARGOCD_WEBHOOK_TOKEN`); 401 on mismatch.
- All credentials in `.env` (gitignored). `.env.example` is the committed template.
- Grafana: anonymous access disabled; PostgreSQL datasource uses `grafana_ro` (SELECT-only).
- CORS on ingest: allow React shell origin only.

## Environment Variables

```
DATABASE_URL=            # postgresql+asyncpg://... for services
GITHUB_WEBHOOK_SECRET=   # HMAC secret, set in GitHub repo settings too
ARGOCD_WEBHOOK_TOKEN=    # shared bearer token for ArgoCD notifications
PROM_URL=                # Prometheus API (port-forward localhost:9090 in dev)
ALERTMANAGER_URL=        # Alertmanager API (localhost:9093 in dev)
BASELINE_WINDOW=30m
OBSERVATION_WINDOW=15m
```

Sample-app chaos flags (per-service env in K8s manifests): `ERROR_RATE` (0–1 float), `LATENCY_MS` (int). Defaults 0/0 = healthy. These create deterministic "bad deploys" for demos.

## Dev Workflow Commands (Makefile targets — build these as you go)

```
make cluster-up / cluster-down   # Kind cluster lifecycle
make up / down                   # docker-compose lifecycle
make forwards / forwards-stop    # port-forwards: Prometheus 9090, Loki 3100, Alertmanager 9093 (PIDs in .pids)
make argocd-forward              # ArgoCD UI at localhost:8443
make logs                        # docker-compose log tail
make db-shell                    # psql into deploylens DB
make tunnel                      # ngrok/cloudflared for GitHub webhook delivery
```

Local ports: Grafana 3000, ingest 8000, React shell 5173, Prometheus 9090, Loki 3100, Alertmanager 9093, ArgoCD 8443.

## GitHub Project Board — Reporting Discipline

**Board:** https://github.com/users/PulithThewmika/projects/3 (Project #3, owner `PulithThewmika`)
**Repo:** `PulithThewmika/deploylens`
**Columns:** Backlog → Todo → In Progress → In Review → Done

Every work session follows this loop:
1. Move the task (and its parent epic, if not already) to **In Progress** before starting.
2. Branch: `git checkout -b feat/E1-T1-kind-cluster` (pattern: `feat/<task-id>-<slug>`).
3. Commit referencing the issue: `feat(infra): create Kind cluster config (#2)`. Use `Closes #N` in the final commit/PR to auto-close.
4. Merge to main → move task to **Done**. When all tasks of an epic are Done, move the epic to Done.

**CLI plumbing for board updates** (item IDs come from `gh project item-list 3 --owner PulithThewmika --format json`):

```bash
gh project item-edit --project-id PVT_kwHOC9Xo4M4BeSZT \
  --id <ITEM_ID> \
  --field-id PVTSSF_lAHOC9Xo4M4BeSZTzhYtwoA \
  --single-select-option-id <OPTION_ID>
```

Status option IDs: Backlog `82eedf92` · Todo `f75ad846` · In Progress `47fc9ee4` · In Review `c89e091d` · Done `98236657`

## Milestones & Epic Map

| Milestone | Gate | Epics |
|---|---|---|
| **M1 — Foundation Ready** (due 2026-07-29) | Webhook → deployment row → Grafana shows metrics | E1 infra, E2 schema, E3 ingest/webhooks, E4 sample app, E5 Grafana base |
| **M2 — Mid Review** | Health scoring + DORA + alerts end-to-end | E6 detection agent, E7 DORA, E8 alerting, E9 REST API |
| **M3 — Interface Layer** | — | E10 MCP server, E11 shell backend, E12 React shell, E13 dashboard suite |
| **M4 — Final Delivery** | — | E14 stretch, E15 Helm packaging, E16 testing, E17 docs/demo |

Issue numbering: epics are `[EPIC-00N]`, tasks are `[EN-TM]`. Issues #1–28 are M1. Task bodies contain acceptance criteria and subtask checklists — treat them as the spec; tick subtasks off in the issue as they complete.

**M1 execution order** (dependency-driven, two parallel tracks):
- Track A (cluster): E1-T1 Kind → E1-T2 Prometheus → E1-T3 Loki → E1-T4 ArgoCD → E4-T2 manifests
- Track B (platform): E1-T5 compose → E2-T1 schema → E2-T2 constraints → E2-T3 image_tag → E2-T5 models → E3-T1 scaffold → E3-T2/T3 webhooks → E3-T4 correlation
- Wiring last: E3-T5/T6 webhook delivery, E4-T3 CI pipeline, E5-T1/T2 Grafana, then P1s (E1-T6 Makefile, E2-T4 DORA views, E4-T4 loadgen)

## Conventions

- **Commits:** Conventional Commits (`feat(scope):`, `fix(scope):`, `chore:`, `docs:`) with issue refs.
- **Python:** async-first (asyncpg, httpx, `asyncio.sleep` for chaos latency); type hints everywhere; SQLAlchemy 2.x style only (no legacy Query API).
- **Migrations:** versioned `V00N__description.sql`, idempotent (safe to run twice), applied via a tracked runner.
- **Tests:** pytest; unit tests live next to each service (`services/<name>/tests/`). Webhook handlers and the correlation engine and health score formula are the priority test surfaces — each task's issue lists the required test cases.
- **Correlation decisions are logged at INFO** — every match (SHA, image_tag fallback, orphan creation, auto-registration) must be traceable in logs.
- **Docker:** each service has its own Dockerfile; images for the sample app go to ghcr.io tagged with short SHA (never `latest`).

## Gotchas

- Windows host (PowerShell + Git Bash): prefer `docker compose` v2 syntax; Kind port mappings must be declared at cluster creation (can't add later without recreate).
- `prometheus-fastapi-instrumentator` does NOT emit a `service` label by default — it must be configured explicitly. Verify with `/metrics` before considering any service task done.
- The GitHub Actions tag-bump commit means `workflow_run.head_sha` (original commit) ≠ ArgoCD revision (bump commit). This is expected — it's why the image_tag fallback exists.
- Prometheus `rate()` returns nothing without steady traffic — the load generator (E4-T4) must be running before health scoring can be tested.
- Grafana provisioned datasources/dashboards only load on container start — restart the Grafana container after editing provisioning YAML.
