# deploylens-agent Helm chart

Customer-side chart: ships container logs (Fluent-Bit → central Loki) and
metrics (bundled agent-mode Prometheus → central Prometheus `remote_write`)
from any Kubernetes cluster, with no dependency on the Prometheus Operator
being pre-installed. See `templates/NOTES.txt` for the post-install runbook.

## E15-T2 validation (clean-cluster install)

Verified 2026-08-31 against a genuinely fresh Kind cluster (`deploylens-agent-validate`,
separate from the `deploylens` dev cluster that already has the sample app,
ArgoCD, etc. installed). **Total time: 354s (~5m54s)**, within the 10-minute
budget — including an unrelated ~4min delay from a stuck `Terminating` pod on
the central cluster's Prometheus (a post-Docker-Desktop-restart artifact, not
part of the chart's own install path; a clean run of just
`kind create cluster` → `helm install` → data confirmed takes well under 2
minutes).

### Prerequisites — expose the central platform

The central platform's Prometheus and Loki (in the `deploylens` Kind
cluster, `monitoring` namespace) are ClusterIP-only by default — not
reachable from a different cluster. For local validation, two things are
needed:

1. **Enable Prometheus's remote-write receiver** (one-time, already
   committed in `deploy/helm-values/kube-prometheus-stack.yaml` as
   `prometheus.prometheusSpec.enableRemoteWriteReceiver: true`). Apply with:
   ```bash
   helm upgrade kps prometheus-community/kube-prometheus-stack \
     -n monitoring --kube-context kind-deploylens \
     -f deploy/helm-values/kube-prometheus-stack.yaml
   ```
2. **Expose Prometheus + Loki as NodePorts** so a sibling Kind cluster (on
   the same `kind` Docker network) can reach them by container IP:
   ```bash
   kubectl --context kind-deploylens apply -f deploy/helm/deploylens-agent/central-platform-nodeports.yaml
   ```

This is a stand-in for "the central platform has a routable endpoint,"
which a real deployment would have via LoadBalancer/Ingress — not something
the chart itself needs to know about.

### Steps (exact commands used)

```bash
# 1. Fresh cluster, separate from the dev cluster
kind create cluster --name deploylens-agent-validate

# 2. Find the central cluster's node container IP (same `kind` Docker network)
docker network inspect kind --format '{{range .Containers}}{{.Name}} {{.IPv4Address}}{{"\n"}}{{end}}'
# -> deploylens-control-plane 172.18.0.2/16

# 3. Install the chart, pointed at the central platform via NodePort
helm install deploylens-agent deploy/helm/deploylens-agent \
  --kube-context kind-deploylens-agent-validate \
  --namespace deploylens-agent --create-namespace \
  --set prometheus.remoteWrite.url="http://172.18.0.2:30090/api/v1/write" \
  --set loki.host="172.18.0.2" \
  --set loki.port=30100 \
  --set webhookTokens.github=<token> \
  --set webhookTokens.argocd=<token> \
  --set webhookTokens.alertmanager=<token>

# 4. Verify: both pods reach Running
kubectl --context kind-deploylens-agent-validate -n deploylens-agent \
  wait --for=condition=Ready pod --all --timeout=120s

# 5. Verify: metrics land in the central Prometheus (cluster label = namespace)
kubectl --context kind-deploylens -n monitoring port-forward svc/kps-kube-prometheus-stack-prometheus 19090:9090 &
curl -s 'http://localhost:19090/api/v1/query?query=up%7Bcluster%3D%22deploylens-agent%22%7D'

# 6. Verify: logs land in central Loki
kubectl --context kind-deploylens -n monitoring port-forward svc/loki 13100:3100 &
curl -s -G "http://localhost:13100/loki/api/v1/query_range" \
  --data-urlencode 'query={cluster="deploylens-agent"}' \
  --data-urlencode "start=$(( $(date +%s) - 600 ))000000000" \
  --data-urlencode "end=$(date +%s)000000000"

# 7. Tear down
kind delete cluster --name deploylens-agent-validate
```

### Results

- `helm install` succeeded, no errors, no manual post-install steps.
- Both pods (`fluent-bit`, `prometheus`) reached `Running`/`Ready` within seconds.
- The bundled Prometheus auto-discovered its own pod via `prometheus.io/scrape`
  annotation (no ServiceMonitor needed) and remote-wrote successfully — confirmed
  by querying the central Prometheus directly for `up{cluster="deploylens-agent"}`.
- Fluent-Bit shipped logs (including `kube-system` pods on the new node) —
  confirmed by querying central Loki for `{cluster="deploylens-agent"}` and
  getting real log lines back within the wait window.
- All within the 5-minute-per-signal acceptance criteria and well inside the
  overall 10-minute budget.

### Cleanup after validation (required, not optional)

`enableRemoteWriteReceiver: true` has no built-in authentication, and the
NodePort Services in `central-platform-nodeports.yaml` bind on the node's
host interface — not just the internal cluster network — so leaving them up
means anything that can reach the Kind node's container IP can write
arbitrary metrics into the central Prometheus, or read/write Loki, with zero
auth. That's an acceptable risk only for the few minutes validation is
actually running. Delete the NodePort Services immediately afterward:
```bash
kubectl --context kind-deploylens -n monitoring delete -f deploy/helm/deploylens-agent/central-platform-nodeports.yaml
```
(`enableRemoteWriteReceiver: true` itself stays enabled — it's needed for
any future validation run and only accepts writes reachable via the
now-deleted NodePorts or from inside the cluster's own pod network.)
