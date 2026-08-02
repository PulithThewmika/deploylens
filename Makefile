.PHONY: cluster-up cluster-down cluster-status up down logs db-shell migrate tunnel webhook-update

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
	docker compose -f deploy/docker-compose.yml exec postgres psql -U deploylens -d deploylens

# --- Migrations ---
migrate:
	python services/ingest/migrations/run.py --url "postgresql://deploylens:deploylens@localhost:5432/deploylens"

# --- Tunnel (GitHub webhook delivery) ---
tunnel:
	ngrok http 8000

webhook-update:
	@NGROK_URL=$$(curl -s http://localhost:4040/api/tunnels | python -c "import sys,json; print(json.load(sys.stdin)['tunnels'][0]['public_url'])") && \
	HOOK_ID=$$(gh api repos/PulithThewmika/deploylens/hooks --jq '.[0].id') && \
	gh api repos/PulithThewmika/deploylens/hooks/$$HOOK_ID --method PATCH \
		-f "config[url]=$$NGROK_URL/webhooks/github" \
		-f "config[content_type]=json" \
		-f "config[secret]=$$(grep GITHUB_WEBHOOK_SECRET .env | cut -d= -f2-)" \
		-f "config[insecure_ssl]=0" && \
	echo "Webhook updated to $$NGROK_URL/webhooks/github"
