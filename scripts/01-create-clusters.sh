#!/usr/bin/env bash
source "$(dirname "$0")/lib.sh"

for c in $CLUSTERS; do
  if kind get clusters 2>/dev/null | grep -qx "$c"; then
    log "$c zaten var, atlanıyor"
    continue
  fi
  log "kind cluster oluşturuluyor: $c"
  # extraMounts mutlak yol ister: __ROOT_DIR__ doldurulur (Windows'ta C:/... biçimi)
  root=$(cd "$ROOT_DIR" && (pwd -W 2>/dev/null || pwd))
  cfg=$(mktemp)
  sed "s|__ROOT_DIR__|$root|g" "$ROOT_DIR/clusters/$c.yaml" > "$cfg"
  kind create cluster --config "$(cd "$(dirname "$cfg")" && (pwd -W 2>/dev/null || pwd))/$(basename "$cfg")" --image "$K8S_NODE_IMAGE"
  rm -f "$cfg"
done

# kind docker ağı ilk cluster ile oluşur; önbellek container'ları bu ağa bağlanır
log "Registry önbelleği ve lab registry"
start_registry_caches
start_lab_registry
for c in $CLUSTERS; do
  configure_node_mirrors "$c"
done

log "Gateway API CRD'leri ($GATEWAY_API_VERSION)"
for c in $CLUSTERS; do
  kubectl --context "$(ctx "$c")" apply -f \
    "https://github.com/kubernetes-sigs/gateway-api/releases/download/${GATEWAY_API_VERSION}/standard-install.yaml"
done
