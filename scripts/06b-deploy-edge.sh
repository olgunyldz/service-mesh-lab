#!/usr/bin/env bash
# Edge (dış DMZ): Kubernetes dışında Docker container'ları.
#
#   host :8080/:8443 -> edge-lb (HAProxy) -> edge-waf (ModSecurity + CRS) -> DMZ ingress gateway (LB IP)
#                       └─────── edge-net ───────┘└──────── kind ağı ────────┘
#
# edge-lb ve loadgen yalnızca edge-net'te; cluster'lara erişemezler. kind ağına yalnızca WAF bağlanır.
source "$(dirname "$0")/lib.sh"

DMZ_GW="http://$(detect_net_prefix).$(lb_octet dmz).10:80"

docker network inspect "$EDGE_NETWORK" >/dev/null 2>&1 || docker network create "$EDGE_NETWORK" >/dev/null
EDGE_SUBNET=$(docker network inspect "$EDGE_NETWORK" -f '{{range .IPAM.Config}}{{.Subnet}}{{end}}')

log "edge-waf (ModSecurity + OWASP CRS, mod=$WAF_MODE) -> $DMZ_GW"
docker rm -f edge-waf >/dev/null 2>&1 || true
docker run -d --name edge-waf --restart unless-stopped --network "$EDGE_NETWORK" \
  -e BACKEND="$DMZ_GW" \
  -e PORT=8080 \
  -e MODSEC_RULE_ENGINE="$WAF_MODE" \
  -e BLOCKING_PARANOIA=1 \
  -e REAL_IP_HEADER=X-Forwarded-For \
  -e SET_REAL_IP_FROM="$EDGE_SUBNET" \
  -e NGINX_X_FORWARDED_PROTO=https \
  -e SERVER_TOKENS=off \
  "$WAF_IMAGE" >/dev/null
docker network connect kind edge-waf

log "edge-lb (HAProxy: TLS, limitler, header temizliği)"
docker rm -f edge-lb >/dev/null 2>&1 || true
docker run -d --name edge-lb --restart unless-stopped --network "$EDGE_NETWORK" \
  -p 8080:8080 -p 8443:8443 \
  -v "$ROOT_DIR/edge/haproxy.cfg:/usr/local/etc/haproxy/haproxy.cfg:ro" \
  -v "$ROOT_DIR/certs/edge/edge.pem:/usr/local/etc/haproxy/certs/edge.pem:ro" \
  "$HAPROXY_IMAGE" >/dev/null

# İnternet istemcisi simülasyonu: Kiali grafiklerinin canlı görünmesi için sürekli trafik.
# Her saniye her hedefe GET, api-a'ya POST /api/echo; her 10 turda bir /status/500.
hosts="api-a.${APPS_DOMAIN}"
has_cluster cluster-b && hosts="$hosts api-b.${APPS_DOMAIN}"

log "loadgen (hedefler: $hosts)"
docker rm -f loadgen >/dev/null 2>&1 || true
docker run -d --name loadgen --restart unless-stopped --network "$EDGE_NETWORK" \
  -e HOSTS="$hosts" \
  -v "$ROOT_DIR/certs/edge/ca.pem:/ca.pem:ro" \
  --entrypoint /bin/sh "$LOADGEN_IMAGE" -c '
    i=0
    while true; do
      i=$((i+1))
      for h in $HOSTS; do
        curl -s -o /dev/null --cacert /ca.pem --resolve "$h:8443:$(getent hosts edge-lb | cut -d" " -f1)" "https://$h:8443/"
        last=$h
      done
      curl -s -o /dev/null --cacert /ca.pem --resolve "api-a.'"$APPS_DOMAIN"':8443:$(getent hosts edge-lb | cut -d" " -f1)" \
        -X POST -d ping "https://api-a.'"$APPS_DOMAIN"':8443/api/echo"
      if [ $((i % 10)) -eq 0 ]; then
        curl -s -o /dev/null --cacert /ca.pem --resolve "$last:8443:$(getent hosts edge-lb | cut -d" " -f1)" "https://$last:8443/status/500"
      fi
      sleep 1
    done' >/dev/null

log "Edge hazır mı?"
for i in $(seq 1 30); do
  # --ssl-no-revoke: Windows curl'ü (schannel) CRL/OCSP kontrolü yapar; lab CA'sının iptal listesi yok
  code=$(env -u MSYS_NO_PATHCONV curl -s -o /dev/null -w '%{http_code}' --max-time 5 --ssl-no-revoke \
    --cacert "$ROOT_DIR/certs/edge/ca.pem" --resolve "api-a.${APPS_DOMAIN}:8443:127.0.0.1" \
    "https://api-a.${APPS_DOMAIN}:8443/healthz" || true)
  [[ "$code" == "200" ]] && { echo "  https://api-a.${APPS_DOMAIN}:8443 -> 200"; break; }
  [[ $i -eq 30 ]] && { echo "  edge yanıt vermedi (son kod: $code)"; exit 1; }
  sleep 2
done
