.PHONY: cluster-up cluster-down cluster-status up down logs db-shell

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
