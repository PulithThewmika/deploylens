.PHONY: cluster-up cluster-down cluster-status

# --- Kind Cluster ---
cluster-up:
	kind create cluster --name deploylens --config deploy/kind-config.yaml

cluster-down:
	kind delete cluster --name deploylens

cluster-status:
	kubectl cluster-info
	kubectl get nodes
