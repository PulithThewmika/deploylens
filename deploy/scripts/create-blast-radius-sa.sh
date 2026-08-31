#!/usr/bin/env bash
# create-blast-radius-sa.sh — provision the read-only ServiceAccount the
# detection agent's blast-radius discovery job (E14-T3) uses to query the
# Kubernetes API of the DeployLens Kind cluster from outside it (the agent
# runs in docker-compose, not in-cluster).
#
# Applies deploy/k8s/blast-radius-rbac.yaml (idempotent) and writes
# K8S_API_SERVER, K8S_TOKEN, K8S_CA_CERT_B64 into .env. Safe to re-run —
# the token Secret is stable as long as the ServiceAccount exists, so this
# just re-reads and re-writes the same values.
#
# On Docker Desktop (Windows/Mac), the agent container reaches the Kind
# API server via host.docker.internal at the host-mapped port — this script
# rewrites the kubeconfig's 127.0.0.1 server address accordingly.
#
# Usage:
#   deploy/scripts/create-blast-radius-sa.sh
#
# Env vars (optional):
#   KUBE_CONTEXT   default kind-deploylens
#   ENV_FILE       default .env (repo root)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

KUBE_CONTEXT="${KUBE_CONTEXT:-kind-deploylens}"
ENV_FILE="${ENV_FILE:-$REPO_ROOT/.env}"

echo "Applying blast-radius RBAC to context ${KUBE_CONTEXT} ..."
kubectl --context "${KUBE_CONTEXT}" apply -f "$REPO_ROOT/deploy/k8s/blast-radius-rbac.yaml"

echo "Waiting for the token Secret to populate ..."
for _ in $(seq 1 15); do
  token=$(kubectl --context "${KUBE_CONTEXT}" -n default get secret deploylens-blast-radius-token -o jsonpath='{.data.token}' 2>/dev/null || true)
  [ -n "$token" ] && break
  sleep 1
done
if [ -z "$token" ]; then
  echo "Token Secret never populated — check the ServiceAccount/Secret in namespace default." >&2
  exit 1
fi
token=$(echo "$token" | base64 -d)

ca_cert_b64=$(kubectl --context "${KUBE_CONTEXT}" -n default get secret deploylens-blast-radius-token -o jsonpath='{.data.ca\.crt}')

# The API server address in kubeconfig (127.0.0.1:<port>) is only reachable
# from the host, not from inside a docker-compose container. Docker Desktop
# resolves host.docker.internal to the host, so swap the host portion.
raw_server=$(kubectl config view --minify --context "${KUBE_CONTEXT}" -o jsonpath='{.clusters[0].cluster.server}')
port="${raw_server##*:}"
api_server="https://host.docker.internal:${port}"

set_env_var() {
  local key="$1" value="$2"
  touch "$ENV_FILE"
  if grep -q "^${key}=" "$ENV_FILE" 2>/dev/null; then
    sed -i.bak "s|^${key}=.*|${key}=${value}|" "$ENV_FILE"
    rm -f "${ENV_FILE}.bak"
  else
    if [ -s "$ENV_FILE" ] && [ "$(tail -c1 "$ENV_FILE")" != "" ]; then
      echo >> "$ENV_FILE"
    fi
    echo "${key}=${value}" >> "$ENV_FILE"
  fi
}

set_env_var "K8S_API_SERVER" "$api_server"
set_env_var "K8S_TOKEN" "$token"
set_env_var "K8S_CA_CERT_B64" "$ca_cert_b64"

echo "Stored K8S_API_SERVER, K8S_TOKEN, K8S_CA_CERT_B64 in ${ENV_FILE}"
echo "API server (as seen from the agent container): ${api_server}"
