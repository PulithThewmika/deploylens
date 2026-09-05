.PHONY: help cluster-up cluster-down cluster-status up down logs db-shell migrate \
        forwards forwards-stop argocd-forward tunnel webhook-update e2e

help:
	@echo "KubeX dev workflow targets:"
	@echo "  cluster-up       Create the Kind cluster from deploy/kind-config.yaml"
	@echo "  cluster-down     Delete the Kind cluster"
	@echo "  cluster-status   Show cluster info and node list"
	@echo "  up               Start docker-compose stack (postgres, ingest, grafana)"
	@echo "  down             Stop docker-compose stack"
	@echo "  logs             Tail docker-compose logs"
	@echo "  db-shell         Open psql into the kubex database"
	@echo "  migrate          Run SQL migrations against local Postgres"
	@echo "  forwards         Start port-forwards for Prometheus, Loki, Alertmanager"
	@echo "  forwards-stop    Stop tracked port-forward processes"
	@echo "  argocd-forward   Port-forward the ArgoCD UI to localhost:8443"
	@echo "  tunnel           Start ngrok tunnel on port 8000 for GitHub webhooks"
	@echo "  webhook-update   Patch the GitHub webhook with the current ngrok URL"
	@echo "  e2e              Run the full push-to-alert end-to-end smoke test (see scripts/e2e_smoke_test.py)"

# --- Kind Cluster ---
cluster-up:
	kind create cluster --name deploylens --config deploy/kind-config.yaml

cluster-down:
	kind delete cluster --name deploylens

cluster-status:
	kubectl cluster-info
	kubectl get nodes

# --- Docker Compose (Central Platform) ---
up:
	docker compose -f deploy/docker-compose.yml --env-file .env up -d

down:
	docker compose -f deploy/docker-compose.yml down

logs:
	docker compose -f deploy/docker-compose.yml logs -f

db-shell:
	docker compose -f deploy/docker-compose.yml exec postgres psql -U kubex -d kubex

# --- Migrations ---
migrate:
	python services/ingest/migrations/run.py --url "postgresql://kubex:$${POSTGRES_PASSWORD:-kubex}@localhost:5432/kubex"

# --- Cluster Port-Forwards (background, PIDs tracked in .pids) ---
forwards:
	@mkdir -p .pids
	@echo "Starting port-forwards..."
	@kubectl -n monitoring port-forward svc/kps-kube-prometheus-stack-prometheus 9090:9090 > .pids/prometheus.log 2>&1 & echo $$! > .pids/prometheus.pid
	@kubectl -n monitoring port-forward svc/loki 3100:3100 > .pids/loki.log 2>&1 & echo $$! > .pids/loki.pid
	@kubectl -n monitoring port-forward svc/kps-kube-prometheus-stack-alertmanager 9093:9093 > .pids/alertmanager.log 2>&1 & echo $$! > .pids/alertmanager.pid
	@sleep 2
	@echo "  Prometheus   -> http://localhost:9090   (pid $$(cat .pids/prometheus.pid))"
	@echo "  Loki         -> http://localhost:3100   (pid $$(cat .pids/loki.pid))"
	@echo "  Alertmanager -> http://localhost:9093   (pid $$(cat .pids/alertmanager.pid))"

forwards-stop:
	@if [ -d .pids ]; then \
		for pidfile in .pids/*.pid; do \
			if [ -f "$$pidfile" ]; then \
				pid=$$(cat $$pidfile); \
				kill $$pid 2>/dev/null && echo "Stopped $$(basename $$pidfile .pid) (pid $$pid)" || echo "Not running: $$(basename $$pidfile .pid)"; \
				rm -f $$pidfile; \
			fi; \
		done; \
	else \
		echo "No .pids directory — nothing to stop"; \
	fi

argocd-forward:
	kubectl -n argocd port-forward svc/argocd-server 8443:443

# --- Tunnel (GitHub webhook delivery) ---
tunnel:
	ngrok http 8000

webhook-update:
	@NGROK_URL=$$(curl -s http://localhost:4040/api/tunnels | python -c "import sys,json; print(json.load(sys.stdin)['tunnels'][0]['public_url'])") && \
	HOOK_ID=$$(gh api repos/PulithThewmika/deploylens-sample-app/hooks --jq '.[0].id') && \
	gh api repos/PulithThewmika/deploylens-sample-app/hooks/$$HOOK_ID --method PATCH \
		-f "config[url]=$$NGROK_URL/webhooks/github" \
		-f "config[content_type]=json" \
		-f "config[secret]=$$(grep GITHUB_WEBHOOK_SECRET .env | cut -d= -f2-)" \
		-f "config[insecure_ssl]=0" && \
	echo "Webhook updated to $$NGROK_URL/webhooks/github"

# --- End-to-End Smoke Test ---
# Requires: cluster-up, up, forwards, and a live tunnel (tunnel + webhook-update)
# already running. Takes ~2-25 minutes — see scripts/e2e_smoke_test.py for why.
e2e:
	python scripts/e2e_smoke_test.py
