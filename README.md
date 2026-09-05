# KubeX
Deployment-aware observability platform — correlates GitHub Actions, ArgoCD, and Kubernetes health per deployment, scores every release autonomously, and exposes the full surface through an MCP interface.

## Development

All common workflow commands are wrapped in the top-level `Makefile`. Run `make help` to see the full list.

### Cluster (Kind)

| Target | What it does |
|---|---|
| `make cluster-up` | Create the Kind cluster from `deploy/kind-config.yaml` |
| `make cluster-down` | Delete the Kind cluster |
| `make cluster-status` | Show cluster info and node list |

### Central Platform (docker-compose)

| Target | What it does |
|---|---|
| `make up` | Start the compose stack (postgres, ingest, grafana) |
| `make down` | Stop the compose stack |
| `make logs` | Tail docker-compose logs |
| `make db-shell` | Open `psql` into the `kubex` database |
| `make migrate` | Run SQL migrations against local Postgres |

### Cluster Port-Forwards

Prometheus, Loki, and Alertmanager run in-cluster but are consumed by services outside the cluster (Grafana, ingest, detection agent). Port-forwards bridge them to the host.

| Target | What it does |
|---|---|
| `make forwards` | Start background port-forwards (Prometheus 9090, Loki 3100, Alertmanager 9093). PIDs tracked in `.pids/` |
| `make forwards-stop` | Kill tracked port-forward processes |
| `make argocd-forward` | Port-forward ArgoCD UI to `localhost:8443` (foreground) |

### GitHub Webhook Tunnel

The ingest service runs locally but needs to receive `workflow_run` events from GitHub. An ngrok tunnel exposes it.

| Target | What it does |
|---|---|
| `make tunnel` | Start ngrok on port 8000 (foreground) |
| `make webhook-update` | Read the active ngrok URL and patch the GitHub repo webhook to point at it |

Typical session flow: `make tunnel` in one terminal, then `make webhook-update` in another once ngrok is up.
