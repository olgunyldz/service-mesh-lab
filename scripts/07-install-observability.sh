#!/usr/bin/env bash
# Merkezi gözlemlenebilirlik (04 · mgmt):
#   - Her cluster'da Prometheus (Istio addon). mgmt dışındakiler metrikleri kendi egress gateway'leri
#     üzerinden mgmt'e remote_write ile gönderir (cluster'lar arası mTLS); yerelde kısa süre saklar.
#   - mgmt'te merkezi Prometheus (remote-write receiver), tek Grafana, tek Kiali (çoklu cluster, salt okunur).
#   - Kiali diğer cluster'ları Kubernetes API'leri üzerinden okur (salt okunur SA; mesh dışı bağlantı).
source "$(dirname "$0")/lib.sh"

ADDONS="https://raw.githubusercontent.com/istio/istio/release-${ISTIO_VERSION%.*}/samples/addons"

helm repo add kiali https://kiali.org/helm-charts >/dev/null 2>&1 || true
helm repo update kiali >/dev/null

# curl ve kubectl Windows programları; MSYS_NO_PATHCONV yüzünden /tmp/... yolunu anlamazlar
TMP=$(cd "$(mktemp -d)" && (pwd -W 2>/dev/null || pwd))
curl -sfL "$ADDONS/prometheus.yaml" -o "$TMP/prometheus.yaml"
curl -sfL "$ADDONS/grafana.yaml" -o "$TMP/grafana.yaml"

# Prometheus yapılandırmasını cluster'a göre üretir.
# Diğer cluster'larda Prometheus agent modunda: yalnızca toplar ve merkeze iletir.
# Merkeze yalnızca Kiali ve Istio panolarının kullandığı metrikler gider (istio_*, pilot_*, up). Hepsi gönderilince
# (envoy/coredns/kiali histogramları) merkezi Prometheus saatler içinde ~1 GB'a çıkıyordu (08 · token-exchange).
# Merkezde saklama 6 saat (lab, bellek bütçesi); uzun süreli saklama gerekirse Thanos/Mimir.
render_prometheus() {
  local c=$1 out="$TMP/prometheus-$1.yaml"
  if [[ $c == mgmt ]]; then
    sed -e "s|^    global:|    global:\n      external_labels:\n        cluster: $c|" \
        -e "s|            - --web.enable-lifecycle|            - --web.enable-lifecycle\n            - --web.enable-remote-write-receiver|" \
        -e "s|--storage.tsdb.retention.time=15d|--storage.tsdb.retention.time=6h|" \
        "$TMP/prometheus.yaml" > "$out"
  else
    sed -e "s|^    global:|    global:\n      external_labels:\n        cluster: $c|" \
        -e "s#^    scrape_configs:#    remote_write:\n      - url: http://prometheus-mgmt.istio-egress.svc.cluster.local/api/v1/write\n        write_relabel_configs:\n          - source_labels: [__name__]\n            regex: 'istio_.*|pilot_.*|up'\n            action: keep\n    scrape_configs:#" \
        `# Agent modu: yerel veritabanı ve sorgu yok, yalnızca toplayıp merkeze gönderir (tam Prometheus ~0,6-1 GB` \
        `# tutuyordu). Agent modu kural dosyalarını desteklemez.` \
        -e "/^    rule_files:/,/^    - \/etc\/config\/alerts/d" \
        -e "s|--storage.tsdb.retention.time=15d|--agent|" \
        -e "s|--storage.tsdb.path=/data|--storage.agent.path=/data|" \
        "$TMP/prometheus.yaml" > "$out"
  fi
  echo "$out"
}

# Kiali'nin uzak cluster'ı okuyabilmesi için kubeconfig secret'ı (mgmt'te)
create_remote_secret() {
  local c=$1 ip ca token
  ip=$(docker inspect -f '{{(index .NetworkSettings.Networks "kind").IPAddress}}' "$c-control-plane")
  ca=$(kubectl config view --raw -o jsonpath="{.clusters[?(@.name==\"kind-$c\")].cluster.certificate-authority-data}")
  token=$(kubectl --context "$(ctx "$c")" -n istio-system create token kiali --duration=8760h)
  cat > "$TMP/kubeconfig-$c" <<EOF
apiVersion: v1
kind: Config
clusters:
  - name: $c
    cluster:
      server: https://$ip:6443
      certificate-authority-data: $ca
users:
  - name: kiali-$c
    user:
      token: $token
contexts:
  - name: $c
    context: {cluster: $c, user: kiali-$c}
current-context: $c
EOF
  kubectl --context "$(ctx mgmt)" -n istio-system create secret generic "kiali-remote-$c" \
    --from-file="$c=$TMP/kubeconfig-$c" --dry-run=client -o yaml \
    | kubectl --context "$(ctx mgmt)" label --local -f - kiali.io/multiCluster=true -o yaml \
    | kubectl --context "$(ctx mgmt)" annotate --local -f - "kiali.io/cluster=$c" -o yaml \
    | kubectl --context "$(ctx mgmt)" apply -f -
}

# 1) Merkezi Prometheus önce (diğerleri ona yazacak)
for c in mgmt $(for x in $CLUSTERS; do [[ $x == mgmt ]] || echo "$x"; done); do
  context=$(ctx "$c")
  log "Prometheus -> $c"
  kubectl --context "$context" apply -f "$(render_prometheus "$c")"
  kubectl --context "$context" -n istio-system rollout status deploy/prometheus --timeout=300s
done

# 2) Uzak cluster'larda Kiali'nin salt okunur kaynakları ve mgmt'te kubeconfig secret'ları
for c in $CLUSTERS; do
  [[ $c == mgmt ]] && continue
  log "Kiali uzak cluster kaynakları (salt okunur SA) -> $c"
  helm upgrade --install kiali-server kiali/kiali-server -n istio-system --kube-context "$(ctx "$c")" \
    --version "$KIALI_VERSION" --set deployment.remote_cluster_resources_only=true --wait >/dev/null
  create_remote_secret "$c"
done

# 3) mgmt: tek Grafana ve tek Kiali
log "Grafana -> mgmt"
kubectl --context "$(ctx mgmt)" apply -f "$TMP/grafana.yaml"
kubectl --context "$(ctx mgmt)" apply -f "$ROOT_DIR/infra/observability/grafana-nodeport.yaml"
kubectl --context "$(ctx mgmt)" -n istio-system rollout status deploy/grafana --timeout=300s

log "Kiali ($KIALI_VERSION, çoklu cluster) -> mgmt"
helm upgrade --install kiali-server kiali/kiali-server -n istio-system --kube-context "$(ctx mgmt)" \
  --version "$KIALI_VERSION" -f "$ROOT_DIR/istio/values/kiali.yaml" \
  --set external_services.grafana.external_url="http://localhost:$GRAFANA_PORT" \
  --wait
