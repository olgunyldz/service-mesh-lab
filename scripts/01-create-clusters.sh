#!/usr/bin/env bash
source "$(dirname "$0")/lib.sh"

for c in $CLUSTERS; do
  if kind get clusters 2>/dev/null | grep -qx "$c"; then
    log "$c zaten var, atlanıyor"
    continue
  fi
  log "kind cluster oluşturuluyor: $c"
  kind create cluster --config "$ROOT_DIR/clusters/$c.yaml" --image "$K8S_NODE_IMAGE"
done

log "Gateway API CRD'leri ($GATEWAY_API_VERSION)"
for c in $CLUSTERS; do
  kubectl --context "$(ctx "$c")" apply -f \
    "https://github.com/kubernetes-sigs/gateway-api/releases/download/${GATEWAY_API_VERSION}/standard-install.yaml"
done
