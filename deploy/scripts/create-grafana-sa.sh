#!/usr/bin/env bash
# create-grafana-sa.sh — provision the Grafana service account used by the
# shell backend's panel proxy (E11-T2/T3).
#
# Creates (or reuses) a Viewer-role service account named
# "deploylens-shell-proxy", mints a token for it, and writes
# GRAFANA_SERVICE_ACCOUNT_TOKEN into .env. Idempotent: re-running it
# reuses the existing service account and skips minting a new token if
# one already exists (Grafana never returns a token's secret value
# again after creation, so we can't silently rotate it without
# invalidating whatever's already in .env).
#
# Usage:
#   deploy/scripts/create-grafana-sa.sh
#
# Env vars (all optional, matching .env / docker-compose defaults):
#   GRAFANA_URL             default http://localhost:3000
#   GRAFANA_ADMIN_USER      default admin
#   GRAFANA_ADMIN_PASSWORD  default deploylens
#   ENV_FILE                default .env (repo root)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

GRAFANA_URL="${GRAFANA_URL:-http://localhost:3000}"
GRAFANA_ADMIN_USER="${GRAFANA_ADMIN_USER:-admin}"
GRAFANA_ADMIN_PASSWORD="${GRAFANA_ADMIN_PASSWORD:-deploylens}"
ENV_FILE="${ENV_FILE:-$REPO_ROOT/.env}"
SA_NAME="deploylens-shell-proxy"

auth=("-u" "${GRAFANA_ADMIN_USER}:${GRAFANA_ADMIN_PASSWORD}")

echo "Waiting for Grafana at ${GRAFANA_URL} ..."
for _ in $(seq 1 30); do
  if curl -sf "${GRAFANA_URL}/api/health" > /dev/null; then
    break
  fi
  sleep 2
done
if ! curl -sf "${GRAFANA_URL}/api/health" > /dev/null; then
  echo "Grafana did not become healthy at ${GRAFANA_URL} — is 'make up' running?" >&2
  exit 1
fi

# ── Find or create the service account (Viewer role only) ──────────
existing_id=$(
  curl -sf "${auth[@]}" \
    "${GRAFANA_URL}/api/serviceaccounts/search?query=${SA_NAME}" \
  | python -c "
import json, sys
data = json.load(sys.stdin)
matches = [sa for sa in data.get('serviceAccounts', []) if sa['name'] == '${SA_NAME}']
print(matches[0]['id'] if matches else '')
"
)

if [ -n "$existing_id" ]; then
  echo "Service account '${SA_NAME}' already exists (id=${existing_id})"
  sa_id="$existing_id"
else
  echo "Creating service account '${SA_NAME}' (Viewer role) ..."
  sa_id=$(
    curl -sf "${auth[@]}" -X POST "${GRAFANA_URL}/api/serviceaccounts" \
      -H "Content-Type: application/json" \
      -d "{\"name\": \"${SA_NAME}\", \"role\": \"Viewer\", \"isDisabled\": false}" \
    | python -c "import json, sys; print(json.load(sys.stdin)['id'])"
  )
  echo "Created service account id=${sa_id}"
fi

# ── Mint a token only if none exists yet (secrets aren't retrievable) ──
token_count=$(
  curl -sf "${auth[@]}" "${GRAFANA_URL}/api/serviceaccounts/${sa_id}/tokens" \
    | python -c "import json, sys; print(len(json.load(sys.stdin)))"
)

if [ "$token_count" -gt 0 ]; then
  echo "Service account already has a token — skipping token creation."
  echo "If you need a fresh token, delete the existing one in Grafana (Administration > Service accounts) and re-run this script."
  exit 0
fi

echo "Minting a token for service account ${sa_id} ..."
token=$(
  curl -sf "${auth[@]}" -X POST "${GRAFANA_URL}/api/serviceaccounts/${sa_id}/tokens" \
    -H "Content-Type: application/json" \
    -d '{"name": "shell-proxy-token"}' \
  | python -c "import json, sys; print(json.load(sys.stdin)['key'])"
)

if [ -z "$token" ]; then
  echo "Failed to mint a service account token." >&2
  exit 1
fi

# ── Store the token in .env (update in place if the key already exists) ──
touch "$ENV_FILE"
if grep -q "^GRAFANA_SERVICE_ACCOUNT_TOKEN=" "$ENV_FILE" 2>/dev/null; then
  # Portable in-place edit for both GNU and BSD sed.
  sed -i.bak "s|^GRAFANA_SERVICE_ACCOUNT_TOKEN=.*|GRAFANA_SERVICE_ACCOUNT_TOKEN=${token}|" "$ENV_FILE"
  rm -f "${ENV_FILE}.bak"
else
  echo "GRAFANA_SERVICE_ACCOUNT_TOKEN=${token}" >> "$ENV_FILE"
fi

echo "Stored GRAFANA_SERVICE_ACCOUNT_TOKEN in ${ENV_FILE}"
