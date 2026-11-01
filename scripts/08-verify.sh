#!/usr/bin/env bash
# Uçtan uca testler. İstemci = host; giriş noktası edge-lb (https://<host>:8443).
source "$(dirname "$0")/lib.sh"

H="$APPS_DOMAIN"
CA="$ROOT_DIR/certs/edge/ca.pem"
PASS=0; FAIL=0

# edge üzerinden istek: edge <host-öneki> <yol> [ek curl argümanları]
# 08'den itibaren kanallar token ister: www ve mobile-api'ye müşteri token'ı otomatik eklenir (NOAUTH=1 ile eklenmez).
edge() {
  local host="$1.$H" path=$2 auth=(); shift 2
  if [[ -z ${NOAUTH:-} ]]; then
    case $host in
      www.*) auth=(-H "Authorization: Bearer ${TW:-}") ;;
      mobile-api.*) auth=(-H "Authorization: Bearer ${TM:-}") ;;
    esac
  fi
  # --ssl-no-revoke: Windows curl'ü (schannel) CRL/OCSP kontrolü yapar; lab CA'sının iptal listesi yok
  env -u MSYS_NO_PATHCONV curl -s --max-time 15 --ssl-no-revoke --cacert "$CA" \
    --resolve "$host:8443:127.0.0.1" "${auth[@]}" "$@" "https://$host:8443$path" || true
}

# --- Kimlik (08): token'lar Keycloak'tan, lab'de direct grant (müşteri, personel) ve client credentials (partner) ---
pwf() { cat "$ROOT_DIR/certs/data/$1.pw" 2>/dev/null; }
kc_token() {  # kc_token <realm> <form argümanları...>: sso host'u üzerinden (edge -> web gateway -> mgmt Keycloak)
  local realm=$1; shift
  env -u MSYS_NO_PATHCONV curl -s --max-time 15 --ssl-no-revoke --cacert "$CA" --resolve "$SSO_HOST:8443:127.0.0.1" \
    "https://$SSO_HOST:8443/realms/$realm/protocol/openid-connect/token" "$@" \
    | sed -n 's/.*"access_token":"\([^"]*\)".*/\1/p'
}
staff_token() {  # personel: şube ağından, cihaz sertifikasıyla, şube gateway'inin /sso/ yolu üzerinden
  MSYS_NO_PATHCONV=1 docker run --rm --network "$BRANCH_NETWORK" -v "$ROOT_DIR/certs/branch:/b:ro" "$LOADGEN_IMAGE" sh -c \
    "curl -s --max-time 15 --cacert /b/ca.pem --cert /b/$BRANCH_DEVICE.crt --key /b/$BRANCH_DEVICE.key \
       --resolve $BRANCH_HOST:443:\$(getent hosts branch-fw | cut -d' ' -f1) \
       https://$BRANCH_HOST/sso/realms/staff/protocol/openid-connect/token -d grant_type=password \
       -d client_id=branch-teller -d username=teller01 --data-urlencode password=$(pwf kc-staff-teller01)" 2>/dev/null \
    | sed -n 's/.*"access_token":"\([^"]*\)".*/\1/p'
}
# Token ömrü 5 dk: her bölümün başında yenilenir
refresh_tokens() {
  TW=$(kc_token customers -d grant_type=password -d client_id=web-bff -d username=ayse --data-urlencode "password=$(pwf kc-customer-ayse)")
  TM=$(kc_token customers -d grant_type=password -d client_id=mobile-app -d username=ayse --data-urlencode "password=$(pwf kc-customer-ayse)")
  TPA=$(kc_token partners -d grant_type=client_credentials -d client_id=acme --data-urlencode "client_secret=$(pwf kc-partner-acme)")
  TPI=$(kc_token partners -d grant_type=client_credentials -d client_id=initech --data-urlencode "client_secret=$(pwf kc-partner-initech)")
  TS=$(staff_token)
}
jwt_payload() {  # base64url JWT gövdesi -> JSON
  local p; p=$(echo "$1" | cut -d. -f2 | tr '_-' '/+')
  while (( ${#p} % 4 )); do p="$p="; done
  echo "$p" | base64 -d 2>/dev/null
}


# Sunucunun belirli bir TLS sürümüne yanıtı (istemci tarafında eski sürümler bilerek açılır)
tls_probe() {
  echo | openssl s_client -connect 127.0.0.1:8443 -servername "www.$H" "-$1" \
    -cipher 'DEFAULT:@SECLEVEL=0' 2>&1 \
    | grep -oE "Protocol *: *TLSv[0-9.]+|alert protocol version" | head -1 || true
}

check() {  # check <açıklama> <beklenen> <gerçek>
  if [[ "$3" == *"$2"* ]]; then
    printf '  \033[32m✔\033[0m %s\n' "$1"; PASS=$((PASS+1))
  else
    printf '  \033[31m✘\033[0m %s (beklenen: %s, gelen: %s)\n' "$1" "$2" "$3"; FAIL=$((FAIL+1))
  fi
}

log "Kimlik sağlayıcı (Keycloak) hazır mı?"
for i in $(seq 1 60); do
  refresh_tokens
  [[ -n $TW && -n $TPA ]] && break
  sleep 5
done
check "Keycloak'tan müşteri, partner ve personel token'ı alınabiliyor" "3" \
  "$( (( ${#TW} > 100 )) && (( ${#TPA} > 100 )) && (( ${#TS} > 100 )) && echo 3 || echo "web=${#TW} partner=${#TPA} personel=${#TS}")"

log "1) İnternet -> edge -> web gateway -> web-bff -> DMZ egress -> cluster-a -> waypoint -> api-a"
check "HTTPS ile api-a'ya ulaşılıyor" '"message": "api-a @ cluster-a"' "$(edge www /)"

log "Edge: TLS ve HTTP"
check "HTTP -> HTTPS yönlendirmesi (301)" "301 https://www.$H:8443/" \
  "$(env -u MSYS_NO_PATHCONV curl -s -o /dev/null -w '%{http_code} %{redirect_url}' --max-time 10 -H "Host: www.$H" http://127.0.0.1:8080/ || true)"
check "HSTS header'ı var" "strict-transport-security: max-age=63072000" \
  "$(edge www / -D - -o /dev/null | tr 'A-Z' 'a-z')"
check "TLS 1.1 sunucu tarafından reddediliyor" "alert protocol version" "$(tls_probe tls1_1)"
check "TLS 1.2 kabul ediliyor" "TLSv1.2" "$(tls_probe tls1_2)"
check "TLS 1.3 kabul ediliyor" "TLSv1.3" "$(tls_probe tls1_3)"

log "Edge: WAF (ModSecurity + OWASP CRS, mod=$WAF_MODE)"
check "XSS denemesi engelleniyor (403)" "403" \
  "$(edge www '/?q=<script>alert(1)</script>' -o /dev/null -w '%{http_code}' -g)"
check "SQL injection denemesi engelleniyor (403)" "403" \
  "$(edge www "/?id=1%27%20OR%20%271%27=%271" -o /dev/null -w '%{http_code}')"

log "Edge: header temizliği"
headers=$(edge www /headers -H "X-Forwarded-For: 6.6.6.6" -H "x-user-jwt: sahte")
check "Sahte X-Forwarded-For içeri geçmiyor" "yok" "$([[ "$headers" == *6.6.6.6* ]] && echo var || echo yok)"
check "Sahte x-user-jwt içeri geçmiyor" "yok" "$([[ "$headers" == *sahte* ]] && echo var || echo yok)"

log "Edge: IP başına istek hızı sınırı (10 sn'de 100)"
limited=$(docker exec loadgen sh -c "ip=\$(getent hosts edge-lb | cut -d' ' -f1); seq 150 | xargs -P 30 -I{} \
  curl -s -o /dev/null -w '%{http_code}\n' --cacert /ca.pem --resolve www.$H:8443:\$ip https://www.$H:8443/ \
  | grep -c 429" || true)
check "Ani 150 istekte 429 dönüyor" "yes" "$([[ ${limited:-0} -gt 0 ]] && echo yes || echo "no (429 sayısı: ${limited:-0})")"

log "Edge: bilgi sızması"
resp=$(edge www /status/500 -D -)
check "5xx gövdesi tek tip (iç ayrıntı yok)" '{"error":"internal_error"}' "$resp"
check "Yanıtta Server / x-envoy header'ı yok" "yok" \
  "$(echo "$resp" | grep -qiE '^(server|x-envoy-upstream-service-time):' && echo var || echo yok)"

log "Edge -> DMZ: karşılıklı TLS"
dmz_probe() {  # kind ağından DMZ ingress'e (edge'i atlayarak) istek
  MSYS_NO_PATHCONV=1 docker run --rm --network kind -v "$ROOT_DIR/certs/edge-dmz:/c:ro" "$LOADGEN_IMAGE" \
    sh -c "curl -s -o /dev/null -w '%{http_code}' --max-time 5 $* || true" 2>/dev/null
}
DMZ_IP="$(detect_net_prefix).$(lb_octet dmz).10"
check "Sertifikasız HTTPS reddediliyor" "000" \
  "$(dmz_probe --cacert /c/ca.pem --resolve www.$H:443:$DMZ_IP https://www.$H/)"
check "Düz HTTP (80) kapalı" "000" "$(dmz_probe -H "'Host: www.$H'" http://$DMZ_IP/)"
check "WAF istemci sertifikasıyla kabul ediliyor (token ile 200)" "200" \
  "$(dmz_probe --cacert /c/ca.pem --cert /c/waf-client.crt --key /c/waf-client.key -H "'Authorization: Bearer $TW'" --resolve www.$H:443:$DMZ_IP https://www.$H/)"

log "Zone geçişi: tek kapı"
apply_rendered "$(ctx dmz)" "$ROOT_DIR/tests/zone-direct-path.yaml" >/dev/null
sleep 5
check "DMZ ingress'ten cluster-a'ya DOĞRUDAN gidiş reddediliyor (403 RBAC)" "403" \
  "$(edge zone-test / -o /dev/null -w '%{http_code}')"
kubectl --context "$(ctx dmz)" delete -f "$ROOT_DIR/tests/zone-direct-path.yaml" >/dev/null
check "DMZ egress üzerinden gidiş kabul ediliyor (200)" "200" \
  "$(edge www / -o /dev/null -w '%{http_code}')"

if has_cluster cluster-b; then
  log "2) İnternet -> ... -> cluster-b -> api-b"
  check "HTTPS ile api-b'ye ulaşılıyor" '"message": "api-b @ cluster-b"' "$(edge api-b /)"
  log "3) api-a -> egress gw (cluster-a) -> cluster-b gw -> api-b"
  check "api-a, api-b'yi çağırıyor" "merhaba" "$(edge www /api/echo -X POST -d merhaba)"
else
  log "2-3) cluster-b kapalı; Akış 2 ve 3 atlandı"
  check "api-a echo (backend yok)" "merhaba" "$(edge www /api/echo -X POST -d merhaba)"
fi

log "DMZ kanalları (web / mobile / partner)"
refresh_tokens
# Partner istekleri Linux curl'lü bir container'dan: Windows curl'ü (schannel) PEM istemci sertifikası kullanamıyor
partner() {  # partner <sertifika adı|-> <curl argümanları>; token: PTOKEN (varsayılan acme), PTOKEN=- token'sız
  local cert="" token=${PTOKEN:-$TPA} auth=""
  [[ $1 != - ]] && cert="--cert /p/$1.crt --key /p/$1.key"
  [[ $token != - ]] && auth='-H "Authorization: Bearer $TOKEN"'
  shift
  MSYS_NO_PATHCONV=1 docker run --rm --network "$EDGE_NETWORK" -e TOKEN="$token" -v "$ROOT_DIR/certs/partner:/p:ro" \
    -v "$ROOT_DIR/certs/edge/ca.pem:/ca.pem:ro" "$LOADGEN_IMAGE" sh -c \
    "curl -s --max-time 10 --cacert /ca.pem $cert $auth --resolve $PARTNER_HOST:8443:\$(getent hosts edge-lb | cut -d' ' -f1) $*" \
    2>/dev/null || true
}
mobile() { local path=$1; shift; edge mobile-api "$path" "$@"; }

check "Web: BFF dashboard (api-a'nın iki ucunu birleştiriyor)" '"channel":"web"' "$(edge www /bff/v1/dashboard)"
check "Web: BFF güvenlik header'ları (CSP, X-Frame-Options)" "x-frame-options: deny" \
  "$(edge www / -D - -o /dev/null | tr 'A-Z' 'a-z')"
check "Web: sahte x-channel ezilip 'web' yazılıyor" '"web"' \
  "$(edge www /headers -H 'x-channel: partner' | grep -A1 -i '"x-channel"')"
check "Web: CORS izinli origin kabul" "access-control-allow-origin: https://www.$H" \
  "$(edge www /api/info -X OPTIONS -H "Origin: https://www.$H" -H 'Access-Control-Request-Method: GET' -D - -o /dev/null | tr 'A-Z' 'a-z')"
check "Web: CORS yabancı origin'e izin yok" "yok" \
  "$(edge www /api/info -X OPTIONS -H 'Origin: https://evil.example.com' -H 'Access-Control-Request-Method: GET' -D - -o /dev/null \
     | grep -qi '^access-control-allow-origin' && echo var || echo yok)"
check "Web: web-bff imzalı image'ın digest'iyle çalışıyor" "$LAB_REGISTRY/lab/web-bff:" \
  "$(kubectl --context "$(ctx dmz)" -n web-bff get pod -l app=web-bff -o jsonpath='{.items[0].spec.containers[0].image}')"
apply_rendered "$(ctx dmz)" "$ROOT_DIR/tests/web-bypass-bff.yaml" >/dev/null
sleep 5
check "Web gateway'den BFF'i atlayıp egress'e çıkış reddediliyor (403 RBAC)" "403" \
  "$(edge bypass-test / -o /dev/null -w '%{http_code}')"
kubectl --context "$(ctx dmz)" delete -f "$ROOT_DIR/tests/web-bypass-bff.yaml" >/dev/null

check "Mobil: /mobile/v1/ -> api-a" '"message": "api-a @ cluster-a"' "$(mobile /mobile/v1/)"
check "Mobil: sahte x-channel ezilip 'mobile' yazılıyor" '"mobile"' \
  "$(mobile /mobile/v1/headers -H 'x-channel: partner' | grep -A1 -i '"x-channel"')"
check "Mobil: kanal dışı yol reddediliyor (403)" "403" "$(mobile /partner/v1/ -o /dev/null -w '%{http_code}')"

check "Partner: acme sertifikasıyla kabul, x-partner-id=acme" '"acme"' \
  "$(partner acme "https://$PARTNER_HOST:8443/partner/v1/headers" | grep -A1 -i '"x-partner-id"')"
check "Partner: izin listesinde olmayan partner (globex) 403" "403" \
  "$(partner globex "-o /dev/null -w '%{http_code}' https://$PARTNER_HOST:8443/partner/v1/")"
check "Partner: sahte x-partner-id header'ı ezilir (globex + 'acme' header'ı -> 403)" "403" \
  "$(partner globex "-H 'x-partner-id: acme' -o /dev/null -w '%{http_code}' https://$PARTNER_HOST:8443/partner/v1/")"
check "Partner: başka CA'dan sertifika edge'de reddediliyor" "000" \
  "$(partner rogue "-o /dev/null -w '%{http_code}' https://$PARTNER_HOST:8443/partner/v1/")"
check "Partner: sertifikasız bağlantı edge'de reddediliyor" "000" \
  "$(partner - "-o /dev/null -w '%{http_code}' https://$PARTNER_HOST:8443/partner/v1/")"
check "Partner: SNI başka host, Host partner (domain fronting) 403" "403" \
  "$(edge www /partner/v1/ -H "Host: $PARTNER_HOST" -o /dev/null -w '%{http_code}')"
limited=$(partner acme "-o /dev/null -D - https://$PARTNER_HOST:8443/partner/v1/ & \
  $(printf 'curl -s --cacert /ca.pem --cert /p/acme.crt --key /p/acme.key -H "Authorization: Bearer $TOKEN" --resolve %s:8443:$(getent hosts edge-lb | cut -d" " -f1) -o /dev/null -D - https://%s:8443/partner/v1/ & ' \
     $(for i in $(seq 29); do echo "$PARTNER_HOST $PARTNER_HOST"; done)) wait" | grep -ci '^x-ratelimit-scope: partner')
check "Partner: kanal kotası aşılınca 429 (gateway, x-ratelimit-scope: partner)" "yes" \
  "$([[ ${limited:-0} -gt 0 ]] && echo yes || echo "no (429 sayısı: ${limited:-0})")"

log "Şube kanalı (şube WAN'ı -> iç firewall -> branch-gateway)"
refresh_tokens
branch() {  # branch <sertifika: device|partner|-> <curl argümanları>; şube ağındaki bir container'dan
  local cert=""
  case $1 in
    device) cert="--cert /b/$BRANCH_DEVICE.crt --key /b/$BRANCH_DEVICE.key" ;;
    partner) cert="--cert /p/acme.crt --key /p/acme.key" ;;
  esac
  shift
  local token=${BTOKEN:-$TS} auth=""
  [[ $token != - ]] && auth='-H "Authorization: Bearer $TOKEN"'
  MSYS_NO_PATHCONV=1 docker run --rm --network "$BRANCH_NETWORK" -e TOKEN="$token" -v "$ROOT_DIR/certs/branch:/b:ro" \
    -v "$ROOT_DIR/certs/partner:/p:ro" "$LOADGEN_IMAGE" sh -c \
    "curl -s --max-time 8 --cacert /b/ca.pem $cert $auth --resolve $BRANCH_HOST:443:\$(getent hosts branch-fw | cut -d' ' -f1) $*" \
    2>/dev/null || true
}
bh=$(branch device "https://$BRANCH_HOST/branch/v1/headers -H 'x-channel: web' -H 'x-branch-device: sahte'")
check "Şube: cihaz sertifikasıyla api-a'ya ulaşılıyor" '"X-Channel"' "$bh"
check "Şube: sahte x-channel ezilip 'branch' yazılıyor" '"branch"' "$(echo "$bh" | grep -A1 -i '"x-channel"')"
check "Şube: cihaz kimliği sertifikadan (x-branch-device)" "CN=$BRANCH_DEVICE" "$(echo "$bh" | grep -A1 -i '"x-branch-device"')"
check "Şube: sertifikasız bağlantı reddediliyor" "000" \
  "$(branch - "-o /dev/null -w '%{http_code}' https://$BRANCH_HOST/branch/v1/")"
check "Şube: başka CA'nın sertifikası (partner) reddediliyor" "000" \
  "$(branch partner "-o /dev/null -w '%{http_code}' https://$BRANCH_HOST/branch/v1/")"
check "Şube: kanal dışı yol reddediliyor (403)" "403" \
  "$(branch device "-o /dev/null -w '%{http_code}' https://$BRANCH_HOST/partner/v1/")"
check "Şube ağından DMZ'nin diğer kapılarına yol yok (web gateway VIP)" "000" \
  "$(MSYS_NO_PATHCONV=1 docker run --rm --network "$BRANCH_NETWORK" "$LOADGEN_IMAGE" curl -sk -o /dev/null -w '%{http_code}' \
     --max-time 5 "https://$(detect_net_prefix).$(lb_octet dmz).$(channel_vip_octet web)/" 2>/dev/null || true)"
code=$(edge www /branch/v1/ -H "Host: $BRANCH_HOST" -o /dev/null -w '%{http_code}')
check "İnternetten şube kanalına ulaşılamıyor (DMZ'de bu host'a kapı yok)" "yok" \
  "$([[ $code == 2* ]] && echo "var ($code)" || echo yok)"

log "4) api-a -> egress gw -> httpbin.org"
check "Çıkış egress gateway'den yapılıyor" "istio-egressgateway" \
  "$(kubectl --context "$(ctx cluster-a)" -n api-a exec deploy/api-a -- wget -qO- -T 10 http://httpbin.org/headers 2>&1 || true)"

log "Bilgi: kayıtsız hedefe doğrudan çıkış (lab kısıtı, test değil)"
direct=$(kubectl --context "$(ctx cluster-a)" -n api-a exec deploy/api-a -- \
  sh -c 'wget -q -O /dev/null -T 8 http://example.com && echo açık || echo kapalı' 2>/dev/null || true)
printf '  \033[33m⚠\033[0m api-a -> example.com (ServiceEntry yok): %s\n' "$direct"
echo "    Ambient'te REGISTRY_ONLY pod'un doğrudan çıkışını engellemez; engel egress NetworkPolicy ile olur,"
echo "    bu lab'da NetworkPolicy uygulanamıyor (bkz. docs/03-hardening.md)."

log "Internal: varsayılan reddet (cluster-a, api-a namespace'inde test pod'u)"
K="kubectl --context $(ctx cluster-a) -n api-a"
# api-a namespace'i yalnızca lab registry'deki imzalı image'ları kabul eder (05 · policy)
PROBE_IMAGE="$LAB_REGISTRY/lab/curl:8.11.1"
$K delete pod authz-probe --ignore-not-found --wait=true >/dev/null 2>&1
$K run authz-probe --image="$PROBE_IMAGE" --restart=Never --overrides='{"spec":{"securityContext":{"runAsNonRoot":true,"runAsUser":100,"seccompProfile":{"type":"RuntimeDefault"}},"containers":[{"name":"p","image":"'"$PROBE_IMAGE"'","command":["sleep","300"],"securityContext":{"allowPrivilegeEscalation":false,"capabilities":{"drop":["ALL"]}}}]}}' >/dev/null
$K wait --for=condition=Ready pod/authz-probe --timeout=90s >/dev/null
pod_ip=$($K get pod -l app=api-a -o jsonpath='{.items[0].status.podIP}')
check "Pod IP ile waypoint'i atlama engelleniyor (ztunnel L4)" "000" \
  "$($K exec authz-probe -- curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://$pod_ip:9898/" 2>/dev/null || true)"
check "Servise yetkisiz kimlikle erişim reddediliyor (waypoint L7, 403)" "RBAC: access denied" \
  "$($K exec authz-probe -- curl -s --max-time 5 http://api-a/ 2>/dev/null || true)"
# Probe mesh sertifikası taşımadığı için ISTIO_MUTUAL el sıkışması başarısız olur (000).
# Mesh kimliği olan ama waypoint olmayan bir istemci ise AuthZ'ye (allow-only-waypoints) takılır.
check "Egress gateway'e waypoint dışından erişilemiyor" "000" \
  "$($K exec authz-probe -- curl -s -o /dev/null -w '%{http_code}' --max-time 5 -k https://istio-egressgateway.istio-egress/ 2>/dev/null || true)"
$K delete pod authz-probe --wait=false >/dev/null

log "Pod Security: gateway ve DMZ kanal namespace'leri restricted"
for c in $CLUSTERS; do
  nss="istio-ingress istio-egress"
  [[ $c == dmz ]] && nss="$nss istio-mobile istio-partner istio-branch web-bff"
  [[ $c == dmz ]] && nss="$nss ratelimit auth"
  [[ $c == cluster-a ]] && nss="$nss account-api"
  [[ $c == mgmt ]] && nss="$nss data iam"
  for ns in $nss; do
    warn=$(kubectl --context "$(ctx "$c")" label ns "$ns" pod-security.kubernetes.io/enforce=restricted \
      --overwrite --dry-run=server 2>&1 | grep -c Warning || true)
    check "$c/$ns: restricted ve ihlal eden pod yok" "0" "$warn"
  done
done

log "5) Mesh durumu (ztunnel, cluster-a)"
check "api-a pod'ları ambient'te (HBONE)" "HBONE" \
  "$(istioctl --context "$(ctx cluster-a)" ztunnel-config workloads 2>/dev/null | grep -E '^api-a +api-a-' | head -1 || true)"
# waypoint-for: service -> waypoint servise bağlı (pod'larda WAYPOINT=None beklenir)
check "api-a servisi waypoint kullanıyor" "waypoint" \
  "$(istioctl --context "$(ctx cluster-a)" ztunnel-config services 2>/dev/null | grep -E '^api-a +api-a ' | head -1 || true)"

log "6) Merkezi gözlemlenebilirlik (mgmt)"
check "Kiali http://localhost:$KIALI_PORT/kiali" "200" "$(http_code "http://localhost:$KIALI_PORT/kiali/api/status")"
check "Grafana http://localhost:$GRAFANA_PORT" "200" "$(http_code "http://localhost:$GRAFANA_PORT/api/health")"

# Merkezi Prometheus'ta her cluster'ın Istio metrikleri var mı (remote_write egress -> mgmt üzerinden)
prom_q() {
  kubectl --context "$(ctx mgmt)" -n istio-system exec deploy/prometheus -c prometheus-server -- \
    wget -qO- "http://localhost:9090/api/v1/query?query=$1" 2>/dev/null || true
}
for c in $CLUSTERS; do
  [[ $c == mgmt ]] && continue
  check "Merkezi Prometheus'ta $c metrikleri var" "\"cluster\":\"$c\"" \
    "$(prom_q "count(up)by(cluster)")"
done
check "Merkezi Prometheus'ta mesh trafik metrikleri (istio_requests_total, cluster-a)" "cluster-a" \
  "$(prom_q "count(istio_requests_total)by(source_cluster)")"

kiali_clusters=$(env -u MSYS_NO_PATHCONV curl -s --max-time 10 "http://localhost:$KIALI_PORT/kiali/api/config" || true)
for c in $CLUSTERS; do
  check "Kiali $c cluster'ını görüyor" "\"$c\"" "$kiali_clusters"
done

check "mgmt girişine mesh sertifikası olmadan erişilemiyor" "000" \
  "$(MSYS_NO_PATHCONV=1 docker run --rm --network kind "$LOADGEN_IMAGE" curl -sk -o /dev/null -w '%{http_code}' --max-time 5 \
     --resolve "$METRICS_HOST:443:$(detect_net_prefix).$(lb_octet mgmt).10" "https://$METRICS_HOST/api/v1/write" 2>/dev/null || true)"

log "8) Veri katmanı (mgmt: PostgreSQL, Valkey; mesh üzerinden)"
refresh_tokens
pg() {  # pg <kullanıcı> <parola dosyası> <sql>: mgmt'teki postgres pod'unda, verilen kullanıcıyla
  kubectl --context "$(ctx mgmt)" -n data exec postgres-0 -- env PGPASSWORD="$(cat "$ROOT_DIR/certs/data/$2.pw")" \
    psql -h 127.0.0.1 -U "$1" -d "$POSTGRES_DB" -tAc "$3" 2>&1 || true
}
vk() {  # vk <kullanıcı> <parola dosyası|-> <komut...>: mgmt'teki valkey pod'unda
  local auth=()
  [[ $2 != - ]] && auth=(--user "$1" --pass "$(cat "$ROOT_DIR/certs/data/$2.pw")")
  shift 2
  kubectl --context "$(ctx mgmt)" -n data exec deploy/valkey -- valkey-cli "${auth[@]}" --no-auth-warning "$@" 2>&1 || true
}

check "Mobil: hesaplar PostgreSQL'den (account-api -> egress -> mgmt)" '"source":"postgresql"' "$(mobile /mobile/v1/accounts)"
check "Web (BFF üzerinden): hesap sorgusu" '"owner":"Acme Ltd."' "$(edge www /accounts/3)"
check "Partner (acme): hesap sorgusu" '"owner":"Acme Ltd."' \
  "$(partner acme "https://$PARTNER_HOST:8443/partner/v1/accounts/3")"
check "IBAN maskeli dönüyor (tam IBAN yanıtta yok)" "yok" \
  "$(mobile /mobile/v1/accounts | grep -q TR190006400000112345678901 && echo var || echo yok)"
check "account-api yalnızca okuma: POST reddediliyor (403, waypoint L7)" "403" \
  "$(mobile /mobile/v1/accounts -X POST -d '{}' -o /dev/null -w '%{http_code}')"

check "PostgreSQL: account_api kendi tablosunu okuyabiliyor" "4" \
  "$(pg account_api pg-account-api 'select count(*) from accounts.accounts')"
check "PostgreSQL: account_api başka şemayı okuyamıyor (audit)" "permission denied" \
  "$(pg account_api pg-account-api 'select * from audit.events')"
check "PostgreSQL: account_api yazamıyor" "permission denied" \
  "$(pg account_api pg-account-api "update accounts.accounts set balance = 0 where id = 1")"

check "Valkey: api-a önbelleği (kendi önekinde yaz/oku)" "verify-ok" \
  "$(mobile /mobile/v1/cache/cache:api-a:verify -X POST -d verify-ok -o /dev/null; mobile /mobile/v1/cache/cache:api-a:verify)"
check "Valkey: api-a başka önekte yazamıyor (ACL)" "cache set failed" \
  "$(mobile /mobile/v1/cache/baska-anahtar -X POST -d x)"
check "Valkey: ratelimit kullanıcısı api-a anahtarlarını okuyamıyor (ACL)" "NOPERM" \
  "$(vk ratelimit valkey-ratelimit GET cache:api-a:verify)"
check "Valkey: kimliksiz (default) kullanıcı kapalı" "NOAUTH" "$(vk - - PING)"

limited=$(PTOKEN=$TPI partner initech "-o /dev/null -D - https://$PARTNER_HOST:8443/partner/v1/accounts & \
  $(printf 'curl -s --cacert /ca.pem --cert /p/initech.crt --key /p/initech.key -H "Authorization: Bearer $TOKEN" --resolve %s:8443:$(getent hosts edge-lb | cut -d" " -f1) -o /dev/null -D - https://%s:8443/partner/v1/accounts & ' \
     $(for i in $(seq 9); do echo "$PARTNER_HOST $PARTNER_HOST"; done)) wait" | grep -ci '^x-envoy-ratelimited: true')
check "Global kota: initech (5/dk) aşınca 429 (ratelimit servisi, sayaç mgmt Valkey'de)" "yes" \
  "$([[ ${limited:-0} -gt 0 ]] && echo yes || echo "no (429 sayısı: ${limited:-0})")"
check "Global kota sayaçları Valkey'de yalnızca rl: önekiyle" "rl:partner_partner_id_" \
  "$(vk admin valkey-admin --scan --pattern 'rl:*' | head -1)"

MGMT_IP="$(detect_net_prefix).$(lb_octet mgmt).10"
for port in 5432 6379; do
  check "mgmt veri girişine ($port) mesh sertifikası olmadan erişilemiyor" "000" \
    "$(MSYS_NO_PATHCONV=1 docker run --rm --network kind "$LOADGEN_IMAGE" curl -sk -o /dev/null -w '%{http_code}' \
       --max-time 5 "https://$MGMT_IP:$port/" 2>/dev/null || true)"
done
check "DMZ egress'te PostgreSQL çıkışı tanımlı değil (yalnızca Valkey 16379)" "16379" \
  "$(kubectl --context "$(ctx dmz)" -n istio-egress get gateway.networking.istio.io data-exit -o jsonpath='{.spec.servers[*].port.number}')"
check "PostgreSQL ve Valkey imzalı image'larla (digest)" "2" \
  "$(kubectl --context "$(ctx mgmt)" -n data get pods -o jsonpath='{range .items[*]}{.spec.containers[0].image}{"\n"}{end}' \
     | grep -c "^$LAB_REGISTRY/lab/.*@sha256:" || true)"

log "9) Kimlik: token doğrulama ve iç JWT (token exchange)"
refresh_tokens
check "Token'sız istek reddediliyor: web (401)" "401" "$(NOAUTH=1 edge www / -o /dev/null -w '%{http_code}')"
check "Token'sız istek reddediliyor: mobil (401)" "401" "$(NOAUTH=1 mobile /mobile/v1/accounts -o /dev/null -w '%{http_code}')"
check "Token'sız istek reddediliyor: partner (401)" "401" \
  "$(PTOKEN=- partner acme "-o /dev/null -w '%{http_code}' https://$PARTNER_HOST:8443/partner/v1/")"
check "Token'sız istek reddediliyor: şube (401)" "401" \
  "$(BTOKEN=- branch device "-o /dev/null -w '%{http_code}' https://$BRANCH_HOST/branch/v1/")"
# Gerçek token'ın gövdesinde yalnızca sub değiştirilir (iss, azp, exp aynı); imza artık tutmaz
tampered="$(echo "$TM" | cut -d. -f1).$(jwt_payload "$TM" | sed 's/"sub":"[^"]*"/"sub":"saldirgan"/' | base64 -w0 | tr '+/' '-_' | tr -d '=').$(echo "$TM" | cut -d. -f3)"
check "Değiştirilmiş token (imza tutmuyor) reddediliyor (401)" "401" \
  "$(NOAUTH=1 mobile /mobile/v1/accounts -H "Authorization: Bearer $tampered" -o /dev/null -w '%{http_code}')"
check "Başka client'ın token'ı (mobil token'ı web kanalında) reddediliyor (403)" "403" \
  "$(NOAUTH=1 edge www / -H "Authorization: Bearer $TM" -o /dev/null -w '%{http_code}')"
check "Müşteri token'ı şube kanalında reddediliyor (403)" "403" \
  "$(BTOKEN=$TM branch device "-o /dev/null -w '%{http_code}' https://$BRANCH_HOST/branch/v1/accounts")"
check "Partner token'ı başka partner'ın sertifikasıyla reddediliyor (acme token + initech sertifikası, 403)" "403" \
  "$(partner initech "-o /dev/null -w '%{http_code}' https://$PARTNER_HOST:8443/partner/v1/accounts")"
check "Personel token'ı + cihaz sertifikası: hesaplar (200)" "200" \
  "$(branch device "-o /dev/null -w '%{http_code}' https://$BRANCH_HOST/branch/v1/accounts")"

hdrs=$(edge www /headers)
check "İç servise x-user-jwt ulaşıyor" '"X-User-Jwt"' "$hdrs"
check "Dış access token (Authorization) içeri girmiyor" "yok" "$(echo "$hdrs" | grep -qi '"Authorization"' && echo var || echo yok)"
ij=$(echo "$hdrs" | grep -A1 '"X-User-Jwt"' | tail -1 | tr -d ' "')
claims=$(jwt_payload "$ij")
check "İç JWT: issuer DMZ'nin (auth.dmz.corp.mesh)" '"iss":"auth.dmz.corp.mesh"' "$claims"
check "İç JWT: audience internal-apis, kanal web, rol customer" '"aud":"internal-apis"' "$claims"
check "İç JWT: kanal ve rol taşınıyor" '"channel":"web"' "$claims"
ttl=$(echo "$claims" | sed -n 's/.*"exp":\([0-9]*\).*/\1/p'); iat=$(echo "$claims" | sed -n 's/.*"iat":\([0-9]*\).*/\1/p')
check "İç JWT: ömür en fazla 5 dk" "yes" "$([[ -n $ttl && -n $iat && $((ttl - iat)) -le 300 ]] && echo yes || echo "no (${ttl:-?}-${iat:-?})")"
pclaims=$(jwt_payload "$(partner acme "https://$PARTNER_HOST:8443/partner/v1/headers" | grep -A1 '"X-User-Jwt"' | tail -1 | tr -d ' "')")
check "İç JWT (partner): partner_id sertifikadan" '"partner_id":"acme"' "$pclaims"
bclaims=$(jwt_payload "$(branch device "https://$BRANCH_HOST/branch/v1/headers" | grep -A1 '"X-User-Jwt"' | tail -1 | tr -d ' "')")
check "İç JWT (şube): cihaz ve rol" '"branch_device":"sube-0001"' "$bclaims"
check "account-api isteği kullanıcıyla logluyor (sub, kanal)" 'channel="mobile"' \
  "$(mobile /mobile/v1/accounts -o /dev/null; kubectl --context "$(ctx cluster-a)" -n account-api logs deploy/account-api --tail=20 2>/dev/null)"

check "Keycloak yönetim konsolu internetten kapalı (/admin, 403)" "403" \
  "$(NOAUTH=1 edge sso /admin/ -o /dev/null -w '%{http_code}')"
check "Keycloak master realm'i internetten kapalı (403)" "403" \
  "$(NOAUTH=1 edge sso /realms/master/protocol/openid-connect/certs -o /dev/null -w '%{http_code}')"
check "İç JWT imza anahtarı yalnızca DMZ'de" "dmz" \
  "$(for c in $CLUSTERS; do kubectl --context "$(ctx "$c")" get secret -A --field-selector metadata.name=auth-signing-key -o name 2>/dev/null | grep -q . && echo -n "$c "; done | xargs)"

log "7) Politika (Kyverno, admission)"
for c in $CLUSTERS; do
  check "$c: 6 politika hazır ve $POLICY_ACTION modunda" "6/6" \
    "$(kubectl --context "$(ctx "$c")" get validatingpolicies,imagevalidatingpolicies -o json 2>/dev/null \
       | grep -cE '"ready": true' || true)/$(kubectl --context "$(ctx "$c")" get validatingpolicies,imagevalidatingpolicies \
       -o jsonpath='{range .items[*]}{.spec.validationActions[0]}{"\n"}{end}' 2>/dev/null | grep -c "$POLICY_ACTION" || true)"
done

# Sunucu tarafı dry-run: admission zincirinden geçer ama pod oluşturulmaz. Çıktı: kabul -> "pod/<ad>", ret -> politika adı
admit() {  # admit <namespace> <image> [pod spec ek alanları] [container ek alanları]
  kubectl --context "$(ctx cluster-a)" -n "$1" run "policy-probe" --image="$2" --restart=Never --dry-run=server -o name \
    --overrides='{"spec":{"securityContext":{"runAsNonRoot":true,"runAsUser":100,"seccompProfile":{"type":"RuntimeDefault"}}'"${3:-}"',"containers":[{"name":"p","image":"'"$2"'","command":["sleep","1"],"securityContext":{"allowPrivilegeEscalation":false,"capabilities":{"drop":["ALL"]}}'"${4:-}"'}]}}' 2>&1 \
    | grep -oE "^pod/policy-probe|Policy [a-z-]+ failed" | head -1 || true
}
C="curlimages/curl:8.11.1"
check "latest tag'li image reddediliyor" "disallow-latest-tag" "$(admit default curlimages/curl:latest)"
check "Tag'siz image reddediliyor" "disallow-latest-tag" "$(admit default curlimages/curl)"
check "privileged container reddediliyor" "disallow-privileged" "$(admit default "$C" '' ',"securityContext":{"privileged":true}')"
check "hostNetwork reddediliyor" "disallow-privileged" "$(admit default "$C" ',"hostNetwork":true')"
check "hostPath volume reddediliyor" "disallow-host-path" "$(admit default "$C" ',"volumes":[{"name":"h","hostPath":{"path":"/etc"}}]')"
check "İzinsiz registry reddediliyor" "restrict-image-registries" "$(admit default evil.example.com/curl:8.11.1)"
check "Kurala uyan pod kabul ediliyor" "pod/policy-probe" "$(admit default "$C")"
check "api-a: lab registry dışından image reddediliyor" "require-lab-registry" "$(admit api-a "$C")"
check "api-a: bizim anahtarla imzasız image reddediliyor" "verify-image-signatures" \
  "$(admit api-a "$LAB_REGISTRY/$LAB_UNSIGNED_IMAGE")"
check "api-a: imzalı image kabul ediliyor" "pod/policy-probe" "$(admit api-a "$PROBE_IMAGE")"
check "api-a pod'ları imzalı image'ın digest'iyle çalışıyor" "$LAB_REGISTRY/lab/podinfo:6.7.1@sha256:" \
  "$(kubectl --context "$(ctx cluster-a)" -n api-a get pod -l app=api-a -o jsonpath='{.items[0].spec.containers[0].image}')"
for c in $CLUSTERS; do
  check "$c: istisnalı sistem bileşenleri çalışıyor (ztunnel, istio-cni, speaker)" "3" \
    "$(kubectl --context "$(ctx "$c")" get ds -A -o jsonpath='{range .items[*]}{.metadata.name}={.status.numberReady}{"\n"}{end}' \
       | grep -cE '^(ztunnel|istio-cni-node|speaker)=[1-9]' || true)"
done

log "Sonuç: $PASS başarılı, $FAIL başarısız"
[[ $FAIL -eq 0 ]]
