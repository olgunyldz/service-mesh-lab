#!/usr/bin/env bash
# Edge (dış DMZ): Kubernetes dışında Docker container'ları.
#
#   host :8080/:8443 -> edge-lb (HAProxy) -> edge-waf (ModSecurity + CRS) -> DMZ kanal gateway'i (Host'a göre LB IP)
#                       └─────── edge-net ───────┘└──────── kind ağı ────────┘
#
# edge-lb ve loadgen yalnızca edge-net'te; cluster'lara erişemezler. kind ağına yalnızca WAF bağlanır.
source "$(dirname "$0")/lib.sh"

# WAF -> DMZ kanal gateway'leri: karşılıklı TLS (Edge-DMZ Zone CA, bkz. 03-generate-certs.sh)
dmz_vip() { echo "$(detect_net_prefix).$(lb_octet dmz).$(channel_vip_octet "$1"):443"; }

docker network inspect "$EDGE_NETWORK" >/dev/null 2>&1 || docker network create "$EDGE_NETWORK" >/dev/null
EDGE_SUBNET=$(docker network inspect "$EDGE_NETWORK" -f '{{range .IPAM.Config}}{{.Subnet}}{{end}}')

log "edge-waf (ModSecurity + OWASP CRS, mod=$WAF_MODE) -> web $(dmz_vip web) · mobile $(dmz_vip mobile) · partner $(dmz_vip partner)"
docker rm -f edge-waf >/dev/null 2>&1 || true
# BACKEND bir nginx değişkeni: hedef, Host'a göre waf-channels.conf.template'teki map'ten gelir
# CORS_*: image her yanıta Allow-Headers, her 403'e "Allow-Origin: *" ekliyor; CORS kararı yalnızca web gateway'inde
docker run -d --name edge-waf --restart unless-stopped --network "$EDGE_NETWORK" \
  -e 'BACKEND=https://$dmz_gateway' \
  -e DMZ_WEB_GW="$(dmz_vip web)" -e DMZ_MOBILE_GW="$(dmz_vip mobile)" -e DMZ_PARTNER_GW="$(dmz_vip partner)" \
  -e MOBILE_HOST="$MOBILE_HOST" -e PARTNER_HOST="$PARTNER_HOST" \
  -e CORS_HEADER_ACCESS_CONTROL_ALLOW_HEADERS= \
  -e CORS_HEADER_403_ALLOW_ORIGIN= -e CORS_HEADER_403_ALLOW_METHODS= -e CORS_HEADER_403_MAX_AGE= \
  -e PORT=8080 \
  -e MODSEC_RULE_ENGINE="$WAF_MODE" \
  -e BLOCKING_PARANOIA=1 \
  -e REAL_IP_HEADER=X-Forwarded-For \
  -e SET_REAL_IP_FROM="$EDGE_SUBNET" \
  -e NGINX_X_FORWARDED_PROTO=https \
  -e SERVER_TOKENS=off \
  -e SERVER_HEADER= \
  -e PROXY_SSL=on \
  -v "$ROOT_DIR/edge/waf-proxy-backend-ssl.conf.template:/etc/nginx/templates/includes/proxy_backend_ssl.conf.template:ro" \
  -v "$ROOT_DIR/edge/waf-channels.conf.template:/etc/nginx/templates/conf.d/channels.conf.template:ro" \
  -v "$ROOT_DIR/certs/edge-dmz:/etc/nginx/edge-dmz:ro" \
  "$WAF_IMAGE" >/dev/null
docker network connect kind edge-waf

log "edge-lb (HAProxy: TLS, limitler, header temizliği)"
docker rm -f edge-lb >/dev/null 2>&1 || true
docker run -d --name edge-lb --restart unless-stopped --network "$EDGE_NETWORK" \
  -p 8080:8080 -p 8443:8443 \
  -v "$ROOT_DIR/edge/haproxy.cfg:/usr/local/etc/haproxy/haproxy.cfg:ro" \
  -v "$ROOT_DIR/edge/crt-list.txt:/usr/local/etc/haproxy/crt-list.txt:ro" \
  -v "$ROOT_DIR/certs/edge/edge.pem:/usr/local/etc/haproxy/certs/edge.pem:ro" \
  -v "$ROOT_DIR/certs/partner/ca.pem:/usr/local/etc/haproxy/certs/partner-ca.pem:ro" \
  "$HAPROXY_IMAGE" >/dev/null

# İnternet istemcisi simülasyonu: Kiali grafiklerinin canlı görünmesi için sürekli trafik.
# Her saniye: web (GET /, POST /api/api/echo, BFF dashboard), mobil (GET /mobile/v1/accounts), partner (acme sertifikasıyla
# GET /partner/v1/); her 10 turda bir web'de /api/status/500. cluster-b aktifse api-b'ye de (cluster-b/21-api-b-route.yaml).
# Mobil ve partner token'ları Keycloak'tan (sso host'u, edge üzerinden), 4 dakikada bir yenilenir (ömür 5 dk): mobil için
# direct grant (lab istisnası), partner için client credentials. Web'de token yok (09a): loadgen tarayıcı gibi giriş yapar
# (/auth/login -> Keycloak giriş formu -> callback) ve oturum cookie'siyle gezer; oturum düşerse yeniden giriş yapar.
# Web yolları token handler'da /api önekini kaybeder: /api/api/echo -> web-bff /api/echo -> api-a (podinfo) /api/echo.
extra=""
has_cluster cluster-b && extra="api-b.${APPS_DOMAIN}"
pwf() { cat "$ROOT_DIR/certs/data/$1.pw" 2>/dev/null || true; }

log "loadgen (web, mobile, partner${extra:+, $extra})"
docker rm -f loadgen >/dev/null 2>&1 || true
docker run -d --name loadgen --restart unless-stopped --network "$EDGE_NETWORK" \
  -e WEB="$WEB_HOST" -e MOBILE="$MOBILE_HOST" -e PARTNER="$PARTNER_HOST" -e SSO="$SSO_HOST" -e EXTRA="$extra" \
  -e CUSTOMER_PW="$(pwf kc-customer-ayse)" -e ACME_SECRET="$(pwf kc-partner-acme)" \
  -v "$ROOT_DIR/certs/edge/ca.pem:/ca.pem:ro" \
  -v "$ROOT_DIR/certs/partner/acme.crt:/partner.crt:ro" \
  -v "$ROOT_DIR/certs/partner/acme.key:/partner.key:ro" \
  --entrypoint /bin/sh "$LOADGEN_IMAGE" -c '
    ip() { getent hosts edge-lb | cut -d" " -f1; }
    req() { h=$1; shift; curl -s -o /dev/null --cacert /ca.pem --resolve "$h:8443:$(ip)" "$@"; }
    token() { r=$1; shift
      curl -s --cacert /ca.pem --resolve "$SSO:8443:$(ip)" "https://$SSO:8443/realms/$r/protocol/openid-connect/token" "$@" \
        | sed -n "s/.*\"access_token\":\"\([^\"]*\)\".*/\1/p"; }
    J=/tmp/web.jar
    c() { curl -s --cacert /ca.pem --resolve "$WEB:8443:$(ip)" --resolve "$SSO:8443:$(ip)" -c $J -b $J "$@"; }
    web_login() {  # tarayıcı gibi: Authorization Code + PKCE (token handler yürütür), giriş formu IdP sayfasında
      rm -f $J
      loc=$(c -o /dev/null -w "%{redirect_url}" "https://$WEB:8443/auth/login")
      action=$(c "$loc" | grep -o "action=\"[^\"]*login-actions/authenticate[^\"]*\"" | head -1 | cut -d\" -f2 | sed "s/&amp;/\&/g")
      cb=$(c -o /dev/null -w "%{redirect_url}" --data-urlencode username=ayse --data-urlencode "password=$CUSTOMER_PW" "$action")
      c -o /dev/null "$cb"
      CSRF=$(c "https://$WEB:8443/auth/session" | sed -n "s/.*\"csrf\":\"\([^\"]*\)\".*/\1/p")
    }
    i=0; last=0
    while true; do
      now=$(date +%s); if [ $((now - last)) -ge 200 ] || [ -z "$TM" ]; then last=$now
        TM=$(token customers -d grant_type=password -d client_id=mobile-app -d username=ayse --data-urlencode "password=$CUSTOMER_PW")
        TP=$(token partners -d grant_type=client_credentials -d client_id=acme --data-urlencode "client_secret=$ACME_SECRET")
      fi
      if [ $((i % 60)) -eq 0 ] && [ "$(c -o /dev/null -w "%{http_code}" "https://$WEB:8443/auth/session")" != 200 ]; then
        web_login
      fi
      i=$((i+1))
      c -o /dev/null "https://$WEB:8443/"
      c -o /dev/null -H "X-CSRF-Token: $CSRF" -X POST -d ping "https://$WEB:8443/api/api/echo"
      c -o /dev/null "https://$WEB:8443/api/bff/v1/dashboard"
      req "$MOBILE" -H "Authorization: Bearer $TM" "https://$MOBILE:8443/mobile/v1/accounts"
      req "$PARTNER" -H "Authorization: Bearer $TP" --cert /partner.crt --key /partner.key "https://$PARTNER:8443/partner/v1/"
      for h in $EXTRA; do req "$h" -H "Authorization: Bearer $TM" "https://$h:8443/"; done
      [ $((i % 10)) -eq 0 ] && c -o /dev/null "https://$WEB:8443/api/status/500"
      sleep 1
    done' >/dev/null

log "Edge hazır mı?"
for i in $(seq 1 30); do
  # --ssl-no-revoke: Windows curl'ü (schannel) CRL/OCSP kontrolü yapar; lab CA'sının iptal listesi yok
  code=$(env -u MSYS_NO_PATHCONV curl -s -o /dev/null -w '%{http_code}' --max-time 5 --ssl-no-revoke \
    --cacert "$ROOT_DIR/certs/edge/ca.pem" --resolve "${WEB_HOST}:8443:127.0.0.1" \
    "https://${WEB_HOST}:8443/healthz" || true)
  [[ "$code" == "200" ]] && { echo "  https://${WEB_HOST}:8443 -> 200"; break; }
  [[ $i -eq 30 ]] && { echo "  edge yanıt vermedi (son kod: $code)"; exit 1; }
  sleep 2
done
