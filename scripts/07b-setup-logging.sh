#!/usr/bin/env bash
# Merkezi loglama (10 · logging). Loki (infra/logging/loki.yaml) burada, diğer her şey ayağa kalktıktan sonra kurulur
# (açılışların çakışması mgmt'i yavaşlatıyordu). Ardından:
#   1) Grafana: kategori başına organizasyon (Apps, Network, Security, DB, Infra), o organizasyonda yalnızca kendi
#      tenant'ının Loki veri kaynağı ve ekip kullanıcısı; yönetici organizasyonunda tüm tenant'lar ("Korelasyon")
#   2) Her cluster'a Fluent Bit (infra/logging/fluent-bit.yaml)
#   3) Edge log toplayıcısı (Docker, infra/logging/edge/)
#   4) Loki panoları (infra/logging/dashboards/): Main Org'a genel bakış, her ekip organizasyonuna kendi kategorisi
#   5) Keycloak yönetim konsolu (http://localhost:8081/admin): master realm'in giriş adresi
# Tekrar çalıştırılabilir: her istek "oluştur ya da güncelle".
source "$(dirname "$0")/lib.sh"

M="kubectl --context $(ctx mgmt) -n logging"
pwf() { cat "$ROOT_DIR/certs/data/$1.pw"; }
LOKI_URL=http://loki.logging.svc.cluster.local:3100
GP=$(pwf grafana-admin)

# gf <metot> <yol> [gövde] [org id]: Grafana API'si (host'tan, yönetici). Gövde stdin'den: Windows'ta komut satırı
# argümanı kod sayfasına çevriliyor ve UTF-8 karakterler (ü, ı, ·) bozuluyordu
gf() {
  local org=() body=()
  [[ -n ${4:-} ]] && org=(-H "X-Grafana-Org-Id: $4")
  [[ -n ${3:-} ]] && body=(--data-binary @-)
  printf '%s' "${3:-}" | env -u MSYS_NO_PATHCONV curl -s -u "admin:$GP" -X "$1" -H 'Content-Type: application/json' \
    "${org[@]}" "${body[@]}" "http://localhost:$GRAFANA_PORT$2"
}
# Loki veri kaynağı: tenant(lar) X-Scope-OrgID başlığıyla (secureJsonData: arayüzde görünmez)
datasource() {  # datasource <uid> <ad> <tenant(lar)> <org id>
  local body
  body="{\"uid\":\"$1\",\"name\":\"$2\",\"type\":\"loki\",\"access\":\"proxy\",\"url\":\"$LOKI_URL\",\"isDefault\":true,
    \"jsonData\":{\"httpHeaderName1\":\"X-Scope-OrgID\",\"maxLines\":1000},\"secureJsonData\":{\"httpHeaderValue1\":\"$3\"}}"
  gf POST /api/datasources "$body" "$4" | grep -q '"id"' || gf PUT "/api/datasources/uid/$1" "$body" "$4" >/dev/null
}

log "Loki -> mgmt/logging"
rendered=$(cat "$ROOT_DIR/infra/logging/loki.yaml")
printf '%s' "$rendered" | sed "s|__CONFIG_HASH__|$(printf '%s' "$rendered" | sha256sum | cut -c1-16)|" \
  | kubectl --context "$(ctx mgmt)" apply -f - >/dev/null
$M rollout status sts/loki --timeout=300s

log "Grafana: kategori başına organizasyon, veri kaynağı ve ekip kullanıcısı"
for i in $(seq 1 60); do
  [[ $(gf GET /api/org) == *'"id":1'* ]] && break
  [[ $i -eq 60 ]] && { echo "  Grafana yanıt vermedi"; exit 1; }
  sleep 5
done
declare -A TITLE=([apps]="Apps" [network]="Network" [security]="Security" [db]="DB" [infra]="Infra")
declare -A USER=([apps]=dev01 [network]=netops01 [security]=soc01 [db]=dba01 [infra]=platform01)
declare -A ORG=()
ALL=$(echo $LOG_CATEGORIES | tr ' ' '|')
# Yönetici (Main Org): tüm tenant'lar birlikte; request_id ile bir isteğin tüm zone'lardaki izi
datasource logs-all "Korelasyon (tüm kategoriler)" "$ALL" 1
echo "  Main Org: Korelasyon (tenant: $ALL)"
for c in $LOG_CATEGORIES; do
  name="${TITLE[$c]}"
  # Aramalar bulamazsa grep boş döner (pipefail): || true
  org=$(gf GET "/api/orgs/name/$name" | grep -o '"id":[0-9]*' | head -1 | cut -d: -f2 || true)
  [[ -z $org ]] && org=$(gf POST /api/orgs "{\"name\":\"$name\"}" | grep -o '"orgId":[0-9]*' | cut -d: -f2 || true)
  datasource "logs-$c" "$name logları" "$c" "$org"
  u=${USER[$c]}
  uid=$(gf GET "/api/users/lookup?loginOrEmail=$u" | grep -o '"id":[0-9]*' | head -1 | cut -d: -f2 || true)
  if [[ -z $uid ]]; then
    uid=$(gf POST /api/admin/users "{\"name\":\"$name ekibi\",\"login\":\"$u\",\"password\":\"$(pwf "grafana-$u")\",\"OrgId\":$org}" \
      | grep -o '"id":[0-9]*' | cut -d: -f2 || true)
  else
    gf PUT "/api/admin/users/$uid/password" "{\"password\":\"$(pwf "grafana-$u")\"}" >/dev/null
  fi
  gf POST "/api/orgs/$org/users" "{\"loginOrEmail\":\"$u\",\"role\":\"Editor\"}" >/dev/null   # zaten üyeyse hata, sorun değil
  gf PATCH "/api/orgs/$org/users/$uid" '{"role":"Editor"}' >/dev/null                        # Explore için Editor
  gf POST "/api/users/$uid/using/$org" >/dev/null
  # Grafana yeni kullanıcıyı Main Org'a Viewer olarak ekler (otomatik atama kapatılırsa her kullanıcıya kişisel
  # organizasyon açıyor); Korelasyon orada olduğu için buradan çıkarılır
  gf DELETE "/api/orgs/1/users/$uid" >/dev/null
  gf POST "/api/orgs/$org/users" '{"loginOrEmail":"admin","role":"Admin"}' >/dev/null   # yönetici tüm organizasyonları görebilsin
  ORG[$c]=$org
  echo "  $name (org $org): veri kaynağı logs-$c (tenant $c), kullanıcı $u"
done

log "Loki panoları"
dashboard() {  # dashboard <json dosyası> <org id>
  gf POST /api/dashboards/db "{\"overwrite\":true,\"dashboard\":$(cat "$1")}" "$2" | grep -o '"url":"[^"]*"' || true
}
echo "  Main Org: $(dashboard "$ROOT_DIR/infra/logging/dashboards/overview.json" 1)"
for c in $LOG_CATEGORIES; do
  echo "  ${TITLE[$c]}: $(dashboard "$ROOT_DIR/infra/logging/dashboards/$c.json" "${ORG[$c]}")"
done

log "Fluent Bit (her cluster, ns logging-agent)"
for c in $CLUSTERS; do
  if [[ $c == mgmt ]]; then host=loki.logging.svc.cluster.local port=3100
  else host=logs-mgmt.istio-egress.svc.cluster.local port=80; fi
  zone=$(kubectl --context "$(ctx "$c")" get ns logging-agent -o jsonpath='{.metadata.labels.zone}')
  rendered=$(sed -e "s|__CLUSTER__|$c|g" -e "s|__ZONE__|$zone|g" -e "s|__LOKI_HOST__|$host|g" -e "s|__LOKI_PORT__|$port|g" \
    "$ROOT_DIR/infra/logging/fluent-bit.yaml")
  hash=$(printf '%s' "$rendered" | sha256sum | cut -c1-16)
  printf '%s' "$rendered" | sed "s|__CONFIG_HASH__|$hash|" | kubectl --context "$(ctx "$c")" apply -f - >/dev/null
  kubectl --context "$(ctx "$c")" -n logging-agent rollout status ds/fluent-bit --timeout=180s >/dev/null
  echo "  $c (zone $zone) -> $host:$port"
done

log "Edge log toplayıcısı (edge-logs: edge-lb, edge-waf, branch-fw -> mgmt, mTLS)"
docker rm -f edge-logs >/dev/null 2>&1 || true
MSYS_NO_PATHCONV=1 docker run -d --name edge-logs --restart unless-stopped --network kind --user 0 \
  --add-host "$LOGS_EDGE_HOST:$(detect_net_prefix).$(lb_octet mgmt).10" \
  --read-only --tmpfs /state --cap-drop ALL --security-opt no-new-privileges \
  -v /var/lib/docker/containers:/dc:ro \
  -v "$ROOT_DIR/infra/logging/edge:/fluent-bit/etc:ro" \
  -v "$ROOT_DIR/certs/logs/ca.pem:/certs/ca.pem:ro" \
  -v "$ROOT_DIR/certs/logs/edge-logs.crt:/certs/edge-logs.crt:ro" \
  -v "$ROOT_DIR/certs/logs/edge-logs.key:/certs/edge-logs.key:ro" \
  "localhost:$LAB_REGISTRY_HOST_PORT/lab/fluent-bit:5.1.3" >/dev/null
echo "  edge-logs -> https://$LOGS_EDGE_HOST (Log CA istemci sertifikası)"

# Keycloak yönetim konsolu (10a): http://localhost:$KEYCLOAK_ADMIN_PORT/admin (mgmt ingress gateway'in yönetim
# dinleyicisi, manifests/mgmt/36-keycloak-admin.yaml). master realm'inin giriş adresi de bu olmalı; yoksa konsol
# sso.apps... adına yönlenir, orada /admin ve master realm DMZ'de kapalı. Uygulama realm'leri etkilenmez
log "Keycloak yönetim konsolu (http://localhost:$KEYCLOAK_ADMIN_PORT/admin)"
kubectl --context "$(ctx mgmt)" -n iam exec deploy/keycloak -- sh -c \
  "/opt/keycloak/bin/kcadm.sh config credentials --server http://localhost:8080 --realm master --user admin \
     --password '$(pwf keycloak-admin)' --config /tmp/kcadm.cfg >/dev/null \
   && /opt/keycloak/bin/kcadm.sh update realms/master -s attributes.frontendUrl=http://localhost:$KEYCLOAK_ADMIN_PORT --config /tmp/kcadm.cfg \
   && rm -f /tmp/kcadm.cfg" >/dev/null
echo "  http://localhost:$KEYCLOAK_ADMIN_PORT/admin  (admin / certs/data/keycloak-admin.pw; yalnızca bu makineden)"

echo "  Grafana: http://localhost:$GRAFANA_PORT (yönetici: admin / certs/data/grafana-admin.pw; ekipler: certs/data/grafana-<kullanıcı>.pw)"
