#!/usr/bin/env bash
# Uçtan uca testler. İstemci = host; giriş noktası edge-lb (https://<host>:8443).
source "$(dirname "$0")/lib.sh"

H="$APPS_DOMAIN"
CA="$ROOT_DIR/certs/edge/ca.pem"
PASS=0; FAIL=0

# edge üzerinden istek: edge <host-öneki> <yol> [ek curl argümanları]
edge() {
  local host="$1.$H" path=$2; shift 2
  # --ssl-no-revoke: Windows curl'ü (schannel) CRL/OCSP kontrolü yapar; lab CA'sının iptal listesi yok
  env -u MSYS_NO_PATHCONV curl -s --max-time 15 --ssl-no-revoke --cacert "$CA" \
    --resolve "$host:8443:127.0.0.1" "$@" "https://$host:8443$path" || true
}

# Sunucunun belirli bir TLS sürümüne yanıtı (istemci tarafında eski sürümler bilerek açılır)
tls_probe() {
  echo | openssl s_client -connect 127.0.0.1:8443 -servername "api-a.$H" "-$1" \
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

log "1) İnternet -> edge-lb -> edge-waf -> DMZ ingress -> DMZ egress -> cluster-a -> waypoint -> api-a"
check "HTTPS ile api-a'ya ulaşılıyor" '"message": "api-a @ cluster-a"' "$(edge api-a /)"

log "Edge: TLS ve HTTP"
check "HTTP -> HTTPS yönlendirmesi (301)" "301 https://api-a.$H:8443/" \
  "$(env -u MSYS_NO_PATHCONV curl -s -o /dev/null -w '%{http_code} %{redirect_url}' --max-time 10 -H "Host: api-a.$H" http://127.0.0.1:8080/ || true)"
check "HSTS header'ı var" "strict-transport-security: max-age=63072000" \
  "$(edge api-a / -D - -o /dev/null | tr 'A-Z' 'a-z')"
check "TLS 1.1 sunucu tarafından reddediliyor" "alert protocol version" "$(tls_probe tls1_1)"
check "TLS 1.2 kabul ediliyor" "TLSv1.2" "$(tls_probe tls1_2)"
check "TLS 1.3 kabul ediliyor" "TLSv1.3" "$(tls_probe tls1_3)"

log "Edge: WAF (ModSecurity + OWASP CRS, mod=$WAF_MODE)"
check "XSS denemesi engelleniyor (403)" "403" \
  "$(edge api-a '/?q=<script>alert(1)</script>' -o /dev/null -w '%{http_code}' -g)"
check "SQL injection denemesi engelleniyor (403)" "403" \
  "$(edge api-a "/?id=1%27%20OR%20%271%27=%271" -o /dev/null -w '%{http_code}')"

log "Edge: header temizliği"
headers=$(edge api-a /headers -H "X-Forwarded-For: 6.6.6.6" -H "x-user-jwt: sahte")
check "Sahte X-Forwarded-For içeri geçmiyor" "yok" "$([[ "$headers" == *6.6.6.6* ]] && echo var || echo yok)"
check "Sahte x-user-jwt içeri geçmiyor" "yok" "$([[ "$headers" == *sahte* ]] && echo var || echo yok)"

log "Edge: IP başına istek hızı sınırı (10 sn'de 100)"
limited=$(docker exec loadgen sh -c "ip=\$(getent hosts edge-lb | cut -d' ' -f1); seq 150 | xargs -P 30 -I{} \
  curl -s -o /dev/null -w '%{http_code}\n' --cacert /ca.pem --resolve api-a.$H:8443:\$ip https://api-a.$H:8443/ \
  | grep -c 429" || true)
check "Ani 150 istekte 429 dönüyor" "yes" "$([[ ${limited:-0} -gt 0 ]] && echo yes || echo "no (429 sayısı: ${limited:-0})")"

log "Edge: bilgi sızması"
resp=$(edge api-a /status/500 -D -)
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
  "$(dmz_probe --cacert /c/ca.pem --resolve api-a.$H:443:$DMZ_IP https://api-a.$H/)"
check "Düz HTTP (80) kapalı" "000" "$(dmz_probe -H "'Host: api-a.$H'" http://$DMZ_IP/)"
check "WAF istemci sertifikasıyla kabul ediliyor" "200" \
  "$(dmz_probe --cacert /c/ca.pem --cert /c/waf-client.crt --key /c/waf-client.key --resolve api-a.$H:443:$DMZ_IP https://api-a.$H/)"

log "Zone geçişi: tek kapı"
apply_rendered "$(ctx dmz)" "$ROOT_DIR/tests/zone-direct-path.yaml" >/dev/null
sleep 5
check "DMZ ingress'ten cluster-a'ya DOĞRUDAN gidiş reddediliyor (403 RBAC)" "403" \
  "$(edge zone-test / -o /dev/null -w '%{http_code}')"
kubectl --context "$(ctx dmz)" delete -f "$ROOT_DIR/tests/zone-direct-path.yaml" >/dev/null
check "DMZ egress üzerinden gidiş kabul ediliyor (200)" "200" \
  "$(edge api-a / -o /dev/null -w '%{http_code}')"

if has_cluster cluster-b; then
  log "2) İnternet -> ... -> cluster-b -> api-b"
  check "HTTPS ile api-b'ye ulaşılıyor" '"message": "api-b @ cluster-b"' "$(edge api-b /)"
  log "3) api-a -> egress gw (cluster-a) -> cluster-b gw -> api-b"
  check "api-a, api-b'yi çağırıyor" "merhaba" "$(edge api-a /api/echo -X POST -d merhaba)"
else
  log "2-3) cluster-b kapalı; Akış 2 ve 3 atlandı"
  check "api-a echo (backend yok)" "merhaba" "$(edge api-a /api/echo -X POST -d merhaba)"
fi

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
$K delete pod authz-probe --ignore-not-found --wait=true >/dev/null 2>&1
$K run authz-probe --image="$LOADGEN_IMAGE" --restart=Never --overrides='{"spec":{"securityContext":{"runAsNonRoot":true,"runAsUser":100,"seccompProfile":{"type":"RuntimeDefault"}},"containers":[{"name":"p","image":"'"$LOADGEN_IMAGE"'","command":["sleep","300"],"securityContext":{"allowPrivilegeEscalation":false,"capabilities":{"drop":["ALL"]}}}]}}' >/dev/null
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

log "Pod Security: gateway namespace'leri restricted"
for c in $CLUSTERS; do
  for ns in istio-ingress istio-egress; do
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

log "6) Gözlemlenebilirlik (Kiali / Grafana)"
for c in $CLUSTERS; do
  check "$c Kiali http://localhost:$(kiali_port "$c")/kiali" "200" "$(http_code "http://localhost:$(kiali_port "$c")/kiali/api/status")"
  check "$c Grafana http://localhost:$(grafana_port "$c")" "200" "$(http_code "http://localhost:$(grafana_port "$c")/api/health")"
done

log "Sonuç: $PASS başarılı, $FAIL başarısız"
[[ $FAIL -eq 0 ]]
