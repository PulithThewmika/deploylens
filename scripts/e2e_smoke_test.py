#!/usr/bin/env python3
"""DeployLens end-to-end smoke test.

Exercises the full deployment pipeline for real, with no mocks: pushes a
commit that raises the payments component's ERROR_RATE chaos flag, then
polls the ingest REST API until ArgoCD's sync creates a deployment record,
the detection agent scores it as degraded/failed from live Prometheus
metrics, and Alertmanager fires an alert on it. This proves the ArgoCD
webhook, correlation engine, health scoring formula, and alerting pipeline
all work together end to end — not just in isolation under mocks.

Note: the ingest DB registers the whole sample app as a single service named
"sample-app" (ArgoCD tracks frontend/orders/payments as one Application, one
GitOps unit — see services.prom_components), not one row per microservice.
Health scoring aggregates error_rate/latency across all three Prometheus
components via max() (see agent/health_score.py:_aggregate_metrics), so a
spike in payments alone still surfaces undiluted in the aggregate. This
script therefore queries the ingest API by service="sample-app", while
still editing only the payments deployment manifest to inject the fault.

Prerequisites (not managed by this script):
  - The Kind cluster and docker-compose stack are up (`make cluster-up`,
    `make up`) with the sample app, ArgoCD, Prometheus and Alertmanager
    running, and the load generator producing steady traffic to payments
    (health scoring needs traffic to compute a meaningful error rate).
  - A tunnel is forwarding GitHub webhooks to the local ingest service
    (`make tunnel`, then `make webhook-update` if the URL changed) — without
    this, the ArgoCD-side webhook still reaches ingest directly (ArgoCD runs
    in-cluster and can reach the host), but this script's git push is what
    triggers ArgoCD's sync in the first place, so this only affects whether
    a matching GitHub-side deployment record exists to correlate against;
    the orphan path handles it either way.

Expected duration: ~2-25 minutes, dominated by two waits outside this
script's control:
  - ArgoCD's git-polling interval (default 3 minutes) before it notices and
    syncs the pushed manifest change.
  - OBSERVATION_WINDOW (15 minutes by default, see .env) that the detection
    agent must wait after a deployment before it has enough post-deploy
    metrics to score it.

Always reverts the ERROR_RATE chaos flag back to 0 on exit — pass, fail, or
Ctrl-C — so the cluster isn't left in a degraded demo state.

Usage:
    python scripts/e2e_smoke_test.py
    python scripts/e2e_smoke_test.py --ingest-url http://localhost:8000
    python scripts/e2e_smoke_test.py --skip-trigger   # poll an already-triggered deploy
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST = REPO_ROOT / "sample-app" / "deploy" / "payments" / "deployment.yaml"
COMPONENT = "payments"  # the manifest/Prometheus label whose chaos flag we set
SERVICE = "sample-app"  # the ingest-registered service that deployment rolls up under
ERROR_RATE_FIELD_RE = re.compile(r'(- name: ERROR_RATE\s*\n\s*value: )"[^"]*"')


def log(msg: str) -> None:
    print(f"[e2e] {time.strftime('%H:%M:%S')} {msg}", flush=True)


def http_get(url: str):
    with urllib.request.urlopen(url, timeout=10) as resp:
        return json.loads(resp.read())


def run(cmd: list[str]) -> str:
    result = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(cmd)}\n{result.stderr}")
    return result.stdout.strip()


def set_error_rate(value: str) -> str | None:
    """Rewrite ERROR_RATE in the payments deployment manifest and push it.

    Returns the new commit SHA, or None if the value was already set (so
    there was nothing to commit).
    """
    original = MANIFEST.read_text()
    updated, count = ERROR_RATE_FIELD_RE.subn(rf'\1"{value}"', original)
    if count != 1:
        raise RuntimeError(
            f"expected exactly one ERROR_RATE field in {MANIFEST}, found {count}"
        )
    if updated == original:
        log(f"ERROR_RATE already {value!r} — nothing to commit")
        return None

    MANIFEST.write_text(updated)
    run(["git", "add", str(MANIFEST)])
    run(["git", "commit", "-m", f"chore(e2e): set payments ERROR_RATE={value} for smoke test"])
    run(["git", "push", "origin", "HEAD:dev"])
    return run(["git", "rev-parse", "HEAD"])


def poll(description: str, timeout_s: int, interval_s: int, check):
    deadline = time.monotonic() + timeout_s
    while True:
        result = check()
        if result is not None:
            return result
        remaining = int(deadline - time.monotonic())
        if remaining <= 0:
            raise TimeoutError(f"timed out after {timeout_s}s waiting for {description}")
        log(f"waiting for {description}... ({remaining}s left)")
        time.sleep(interval_s)


def nudge_argocd_refresh() -> None:
    """Best-effort: force an immediate ArgoCD reconciliation instead of
    waiting out its default ~3min git-polling interval. Not required for
    correctness — just speeds up the test. Silently skipped if kubectl
    isn't available or the annotate call fails for any reason."""
    try:
        subprocess.run(
            [
                "kubectl", "-n", "argocd", "annotate", "application", "sample-app",
                "argocd.argoproj.io/refresh=hard", "--overwrite",
            ],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        pass


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--ingest-url", default="http://localhost:8000")
    parser.add_argument(
        "--deploy-timeout", type=int, default=300,
        help="seconds to wait for the new deployment to appear (default 300 = 5m)",
    )
    parser.add_argument(
        "--assess-timeout", type=int, default=1200,
        help="seconds to wait for the health assessment (default 1200 = 20m, "
             "i.e. OBSERVATION_WINDOW + margin)",
    )
    parser.add_argument("--poll-interval", type=int, default=10)
    parser.add_argument(
        "--skip-trigger", action="store_true",
        help="skip pushing the ERROR_RATE commit; poll against an already-triggered deployment",
    )
    parser.add_argument(
        "--skip-cleanup", action="store_true",
        help="leave ERROR_RATE=0.3 in place after the test, for manual inspection",
    )
    args = parser.parse_args()

    try:
        baseline = http_get(f"{args.ingest_url}/api/deployments?service={SERVICE}&limit=1")
    except urllib.error.URLError as exc:
        log(f"FAIL — cannot reach ingest at {args.ingest_url}: {exc}")
        return 1
    baseline_id = baseline[0]["id"] if baseline else 0
    log(f"baseline: latest {SERVICE} deployment id = {baseline_id}")

    pushed_sha = None
    try:
        if not args.skip_trigger:
            log("Step 1/4: pushing ERROR_RATE=0.3 to sample-app/deploy/payments/deployment.yaml")
            pushed_sha = set_error_rate("0.3")
            log(f"pushed {pushed_sha}")
            nudge_argocd_refresh()
        else:
            log("Step 1/4: skipped (--skip-trigger)")

        log("Step 2/4: waiting for a new deployment to appear via ArgoCD sync")

        def find_new_deployment():
            rows = http_get(f"{args.ingest_url}/api/deployments?service={SERVICE}&limit=5")
            newer = [r for r in rows if r["id"] > baseline_id]
            return newer[0] if newer else None

        new_deploy = poll("new deployment", args.deploy_timeout, args.poll_interval, find_new_deployment)
        deploy_id = new_deploy["id"]
        log(f"new deployment detected: id={deploy_id} status={new_deploy['status']}")

        log(f"Step 3/4: waiting for deployment {deploy_id} to reach status=assessed")

        def check_assessed():
            detail = http_get(f"{args.ingest_url}/api/deployments/{deploy_id}")
            return detail if detail["status"] == "assessed" else None

        assessed = poll(
            f"deployment {deploy_id} assessment", args.assess_timeout, args.poll_interval, check_assessed,
        )
        health = assessed.get("health_assessment") or {}
        score, verdict = health.get("score"), health.get("verdict")
        log(f"assessed: score={score} verdict={verdict}")

        if verdict not in ("degraded", "failed"):
            raise AssertionError(
                f"expected verdict in ('degraded', 'failed') for ERROR_RATE=0.3, "
                f"got {verdict!r} (score={score})"
            )

        log("Step 4/4: checking for an active alert")
        alerts = http_get(f"{args.ingest_url}/api/alerts?active=true&service={SERVICE}")
        if not alerts:
            raise AssertionError(f"expected at least one active alert for {SERVICE}, found none")
        log(f"active alert found: {alerts[0]['title']}")

        log("PASS — verified push -> ArgoCD sync -> correlation -> health scoring -> alert")
        return 0

    except Exception as exc:
        log(f"FAIL — {exc}")
        return 1

    finally:
        if pushed_sha and not args.skip_cleanup:
            log("cleanup: reverting ERROR_RATE back to 0")
            try:
                set_error_rate("0")
            except Exception as exc:
                log(f"cleanup FAILED — manually revert {MANIFEST}: {exc}")


if __name__ == "__main__":
    sys.exit(main())
