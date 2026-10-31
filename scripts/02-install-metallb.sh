#!/usr/bin/env bash
source "$(dirname "$0")/lib.sh"

prefix=$(detect_net_prefix)
log "kind docker ağı: ${prefix}.0.0/16"

for c in $CLUSTERS; do
  context=$(ctx "$c")
  pool="${prefix}.$(lb_octet "$c")"
  log "MetalLB -> $c (havuz ${pool}.10-50)"
  kubectl --context "$context" apply -f \
    "https://raw.githubusercontent.com/metallb/metallb/${METALLB_VERSION}/config/manifests/metallb-native.yaml"
  kubectl --context "$context" -n metallb-system wait --for=condition=Available deploy --all --timeout=180s
  kubectl --context "$context" -n metallb-system rollout status ds/speaker --timeout=180s
  sed "s/__POOL_PREFIX__/${pool}/g" "$ROOT_DIR/infra/metallb/ipaddresspool.yaml" \
    | kubectl --context "$context" apply -f -
done
