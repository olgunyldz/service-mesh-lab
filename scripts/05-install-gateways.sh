#!/usr/bin/env bash
# DMZ: dmz-ingressgateway (edge-waf'tan gelen trafik) + dmz-egressgateway (internal'a tek kapı)
# Internal cluster'lar: istio-ingressgateway (yalnızca DMZ egress'ten) + istio-egressgateway
source "$(dirname "$0")/lib.sh"

V="$ROOT_DIR/istio/values"
prefix=$(detect_net_prefix)

install_ingress() {
  local c=$1 name=$2; shift 2
  local ip="${prefix}.$(lb_octet "$c").10"
  log "$name -> $c (LB IP $ip)"
  kubectl --context "$(ctx "$c")" create namespace istio-ingress --dry-run=client -o yaml \
    | kubectl --context "$(ctx "$c")" apply -f -
  helm upgrade --install "$name" istio/gateway -n istio-ingress --kube-context "$(ctx "$c")" \
    --version "$ISTIO_VERSION" -f "$V/ingress-gateway.yaml" "$@" \
    --set-string "service.annotations.metallb\.io/loadBalancerIPs=$ip" \
    --wait
}

install_egress() {
  local c=$1 name=$2
  log "$name -> $c"
  kubectl --context "$(ctx "$c")" create namespace istio-egress --dry-run=client -o yaml \
    | kubectl --context "$(ctx "$c")" apply -f -
  helm upgrade --install "$name" istio/gateway -n istio-egress --kube-context "$(ctx "$c")" \
    --version "$ISTIO_VERSION" -f "$V/egress-gateway.yaml" \
    --wait
}

install_ingress dmz dmz-ingressgateway -f "$V/ingress-gateway-dmz.yaml"
install_egress dmz dmz-egressgateway

for c in $(internal_clusters); do
  install_ingress "$c" istio-ingressgateway
  install_egress "$c" istio-egressgateway
done
