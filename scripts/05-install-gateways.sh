#!/usr/bin/env bash
# DMZ: kanal gateway'leri (edge-waf'tan gelen trafik) + dmz-egressgateway (internal'a tek kapı)
#   web: dmz-ingressgateway (istio-ingress) · mobile: mobile-gateway (istio-mobile) · partner: partner-gateway (istio-partner)
#   branch: branch-gateway (istio-branch; edge yok, şube iç firewall'undan gelir)
# Internal cluster'lar: istio-ingressgateway (yalnızca DMZ egress'ten) + istio-egressgateway
source "$(dirname "$0")/lib.sh"

V="$ROOT_DIR/istio/values"
prefix=$(detect_net_prefix)

# install_ingress <cluster> <ad> [--ns <namespace>] [--octet <son oktet>] [helm argümanları]
install_ingress() {
  local c=$1 name=$2; shift 2
  local ns=istio-ingress octet=10
  [[ ${1:-} == --ns ]] && { ns=$2; shift 2; }
  [[ ${1:-} == --octet ]] && { octet=$2; shift 2; }
  local ip="${prefix}.$(lb_octet "$c").$octet"
  log "$name -> $c/$ns (LB IP $ip)"
  helm upgrade --install "$name" istio/gateway -n "$ns" --kube-context "$(ctx "$c")" \
    --version "$ISTIO_VERSION" -f "$V/ingress-gateway.yaml" "$@" \
    --set-string "service.annotations.metallb\.io/loadBalancerIPs=$ip" \
    --wait
}

install_egress() {
  local c=$1 name=$2
  log "$name -> $c"
  helm upgrade --install "$name" istio/gateway -n istio-egress --kube-context "$(ctx "$c")" \
    --version "$ISTIO_VERSION" -f "$V/egress-gateway.yaml" \
    --wait
}

# Namespace'ler etiketleriyle (Pod Security restricted vb.) gateway pod'larından ÖNCE oluşturulur;
# etiket sonradan eklenirse mevcut pod'lar denetlenmez.
for c in $CLUSTERS; do
  log "Namespace'ler -> $c"
  apply_rendered "$(ctx "$c")" "$ROOT_DIR/manifests/$c/00-namespaces.yaml"
done

# Her kanal gateway'i edge-waf'ı aynı Edge-DMZ Zone CA ile doğrular; secret her namespace'te ayrı
log "DMZ kanal gateway'leri mTLS secret'ı (Edge-DMZ Zone CA)"
for ns in istio-ingress istio-mobile istio-partner; do
  kubectl --context "$(ctx dmz)" -n "$ns" create secret generic dmz-ingress-mtls \
    --from-file=tls.crt="$ROOT_DIR/certs/edge-dmz/dmz-server.crt" \
    --from-file=tls.key="$ROOT_DIR/certs/edge-dmz/dmz-server.key" \
    --from-file=ca.crt="$ROOT_DIR/certs/edge-dmz/ca.pem" \
    --dry-run=client -o yaml | kubectl --context "$(ctx dmz)" apply -f -
done

install_ingress dmz dmz-ingressgateway --octet "$(channel_vip_octet web)" -f "$V/ingress-gateway-dmz.yaml"
install_ingress dmz mobile-gateway --ns istio-mobile --octet "$(channel_vip_octet mobile)" -f "$V/ingress-gateway-dmz.yaml"
install_ingress dmz partner-gateway --ns istio-partner --octet "$(channel_vip_octet partner)" -f "$V/ingress-gateway-dmz.yaml"

# Şube kanalı: kendi sunucu sertifikası (iç alan adı) ve terminalleri doğrulayan Branch CA.
# Önünde HTTP proxy yok (iç firewall TCP iletir), bu yüzden ingress-gateway-dmz.yaml (numTrustedProxies) kullanılmaz.
kubectl --context "$(ctx dmz)" -n istio-branch create secret generic branch-gateway-mtls \
  --from-file=tls.crt="$ROOT_DIR/certs/branch/gateway.crt" \
  --from-file=tls.key="$ROOT_DIR/certs/branch/gateway.key" \
  --from-file=ca.crt="$ROOT_DIR/certs/branch/ca.pem" \
  --dry-run=client -o yaml | kubectl --context "$(ctx dmz)" apply -f -
install_ingress dmz branch-gateway --ns istio-branch --octet "$(channel_vip_octet branch)"
install_egress dmz dmz-egressgateway

for c in $(internal_clusters); do
  install_ingress "$c" istio-ingressgateway
  install_egress "$c" istio-egressgateway
done
