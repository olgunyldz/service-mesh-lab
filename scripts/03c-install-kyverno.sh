#!/usr/bin/env bash
# Kyverno (admission controller) + politikalar + istisnalar. Istio'dan önce kurulur: sonraki tüm pod'lar denetimden geçer.
# Kullanım: 03c-install-kyverno.sh [Deny|Audit]   (varsayılan: config.env POLICY_ACTION)
source "$(dirname "$0")/lib.sh"

ACTION=${1:-$POLICY_ACTION}
PUB="$ROOT_DIR/certs/cosign/cosign.pub"
[[ -f "$PUB" ]] || { echo "cosign.pub yok, önce 03-generate-certs.sh"; exit 1; }

helm repo add kyverno https://kyverno.github.io/kyverno/ --force-update >/dev/null

render_policies() {
  # Açık anahtar YAML block scalar içinde 12 boşluk girintiyle
  local key; key=$(sed 's/^/            /' "$PUB")
  awk -v key="$key" '{ if ($0 == "__COSIGN_PUB__") print key; else print }' "$ROOT_DIR/infra/kyverno/policies.yaml" \
    | sed -e "s/__ACTION__/$ACTION/g" -e "s/__LAB_REGISTRY__/$LAB_REGISTRY/g"
}

for c in $CLUSTERS; do
  context=$(ctx "$c")
  log "Kyverno $KYVERNO_CHART_VERSION: $c"
  helm upgrade --install kyverno kyverno/kyverno --kube-context "$context" \
    --version "$KYVERNO_CHART_VERSION" -n kyverno --create-namespace \
    -f "$ROOT_DIR/infra/kyverno/values.yaml" --wait --timeout 5m >/dev/null

  log "Politikalar ($ACTION) ve istisnalar: $c"
  # Pod Ready olsa da Kyverno'nun politika webhook'u birkaç saniye bağlantı reddedebiliyor; hazır olana kadar dene
  for i in $(seq 1 30); do
    render_policies | kubectl --context "$context" apply -f - 2>/dev/null \
      && kubectl --context "$context" apply -f "$ROOT_DIR/infra/kyverno/exceptions.yaml" 2>/dev/null && break
    [[ $i -eq 30 ]] && { echo "politikalar uygulanamadı"; exit 1; }
    echo "  Kyverno webhook'u henüz hazır değil, tekrar deneniyor ($i)"; sleep 5
  done

  # Politika webhook'a yüklenmeden oluşturulan pod denetlenmez; hazır olmasını bekle
  for i in $(seq 1 30); do
    not_ready=$(kubectl --context "$context" get validatingpolicies,imagevalidatingpolicies \
      -o jsonpath='{range .items[*]}{.metadata.name}={.status.conditionStatus.ready}{"\n"}{end}' | grep -vc "=true$" || true)
    [[ "$not_ready" == 0 ]] && break
    sleep 2
  done
  kubectl --context "$context" get validatingpolicies,imagevalidatingpolicies
done
