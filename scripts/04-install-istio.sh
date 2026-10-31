#!/usr/bin/env bash
# Her cluster'a Istio ambient: base -> istiod -> istio-cni -> ztunnel
source "$(dirname "$0")/lib.sh"

helm repo add istio https://istio-release.storage.googleapis.com/charts >/dev/null 2>&1 || true
helm repo update istio >/dev/null

V="$ROOT_DIR/istio/values"

for c in $CLUSTERS; do
  context=$(ctx "$c")
  net=$(network_of "$c")
  log "Istio ambient ($ISTIO_VERSION) -> $c"

  kubectl --context "$context" label namespace istio-system topology.istio.io/network="$net" --overwrite

  helm upgrade --install istio-base istio/base -n istio-system --kube-context "$context" \
    --version "$ISTIO_VERSION" --wait

  helm upgrade --install istiod istio/istiod -n istio-system --kube-context "$context" \
    --version "$ISTIO_VERSION" -f "$V/istiod.yaml" \
    --set global.meshID="$MESH_ID" \
    --set global.multiCluster.clusterName="$c" \
    --set global.network="$net" \
    --set meshConfig.trustDomain="$TRUST_DOMAIN" \
    --wait

  helm upgrade --install istio-cni istio/cni -n istio-system --kube-context "$context" \
    --version "$ISTIO_VERSION" -f "$V/cni.yaml" --wait

  helm upgrade --install ztunnel istio/ztunnel -n istio-system --kube-context "$context" \
    --version "$ISTIO_VERSION" -f "$V/ztunnel.yaml" \
    --set multiCluster.clusterName="$c" \
    --set network="$net" \
    --wait
done
