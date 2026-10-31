#!/usr/bin/env bash
# DMZ: dmz-ingressgateway (public)
# cluster-a/b: istio-ingressgateway (internal, sadece DMZ'den) + istio-egressgateway
source "$(dirname "$0")/lib.sh"

V="$ROOT_DIR/istio/values"
prefix=$(detect_net_prefix)

install_ingress() {
  local c=$1 name=$2
  local ip="${prefix}.$(lb_octet "$c").10"
  log "$name -> $c (LB IP $ip)"
  kubectl --context "$(ctx "$c")" create namespace istio-ingress --dry-run=client -o yaml \
    | kubectl --context "$(ctx "$c")" apply -f -
  helm upgrade --install "$name" istio/gateway -n istio-ingress --kube-context "$(ctx "$c")" \
    --version "$ISTIO_VERSION" -f "$V/ingress-gateway.yaml" \
    --set-string "service.annotations.metallb\.io/loadBalancerIPs=$ip" \
    --wait
}

install_egress() {
  local c=$1
  log "istio-egressgateway -> $c"
  kubectl --context "$(ctx "$c")" create namespace istio-egress --dry-run=client -o yaml \
    | kubectl --context "$(ctx "$c")" apply -f -
  helm upgrade --install istio-egressgateway istio/gateway -n istio-egress --kube-context "$(ctx "$c")" \
    --version "$ISTIO_VERSION" -f "$V/egress-gateway.yaml" \
    --wait
}

install_ingress dmz dmz-ingressgateway

for c in $(internal_clusters); do
  install_ingress "$c" istio-ingressgateway
  install_egress "$c"
done
