#!/usr/bin/env bash
# Her cluster'a Prometheus + Grafana (Istio addon'ları) ve Kiali kurar.
# Erişim: Kiali http://localhost:<kiali_port>/kiali , Grafana http://localhost:<grafana_port>
source "$(dirname "$0")/lib.sh"

ADDONS="https://raw.githubusercontent.com/istio/istio/release-${ISTIO_VERSION%.*}/samples/addons"

helm repo add kiali https://kiali.org/helm-charts >/dev/null 2>&1 || true
helm repo update kiali >/dev/null

# curl ve kubectl Windows programları; MSYS_NO_PATHCONV yüzünden /tmp/... yolunu anlamazlar
TMP=$(cd "$(mktemp -d)" && (pwd -W 2>/dev/null || pwd))
curl -sfL "$ADDONS/prometheus.yaml" -o "$TMP/prometheus.yaml"
curl -sfL "$ADDONS/grafana.yaml" -o "$TMP/grafana.yaml"

for c in $CLUSTERS; do
  context=$(ctx "$c")
  log "Prometheus + Grafana -> $c"
  kubectl --context "$context" apply -f "$TMP/prometheus.yaml"
  kubectl --context "$context" apply -f "$TMP/grafana.yaml"
  kubectl --context "$context" apply -f "$ROOT_DIR/infra/observability/grafana-nodeport.yaml"
  # Kiali, Prometheus hazır olmadan açılırsa graph boş kalabiliyor; önce bekle
  kubectl --context "$context" -n istio-system rollout status deploy/prometheus --timeout=300s
  kubectl --context "$context" -n istio-system rollout status deploy/grafana --timeout=300s

  log "Kiali ($KIALI_VERSION) -> $c"
  helm upgrade --install kiali-server kiali/kiali-server -n istio-system --kube-context "$context" \
    --version "$KIALI_VERSION" -f "$ROOT_DIR/istio/values/kiali.yaml" \
    --set external_services.grafana.external_url="http://localhost:$(grafana_port "$c")" \
    --wait
done
