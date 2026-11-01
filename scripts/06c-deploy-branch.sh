#!/usr/bin/env bash
# Şube kanalı (Kubernetes dışı kısım): şube WAN'ı, iç firewall ve bir şube terminali.
#
#   branch-terminal --(branch-net)--> branch-fw (TCP 443) --(kind ağı)--> branch-gateway (DMZ LB IP)
#
# İnternet edge'inden (edge-net) tamamen ayrı. Terminal yalnızca branch-net'te; kind ağına yalnızca branch-fw bağlı.
source "$(dirname "$0")/lib.sh"

BRANCH_GW="$(detect_net_prefix).$(lb_octet dmz).$(channel_vip_octet branch):443"

docker network inspect "$BRANCH_NETWORK" >/dev/null 2>&1 || docker network create "$BRANCH_NETWORK" >/dev/null

log "branch-fw (iç firewall: yalnızca TCP 443 -> $BRANCH_GW)"
docker rm -f branch-fw >/dev/null 2>&1 || true
docker run -d --name branch-fw --restart unless-stopped --network "$BRANCH_NETWORK" \
  -e BRANCH_GW="$BRANCH_GW" \
  -v "$ROOT_DIR/edge/branch-fw.cfg:/usr/local/etc/haproxy/haproxy.cfg:ro" \
  "$HAPROXY_IMAGE" >/dev/null
docker network connect kind branch-fw

# Şube terminali: gişe uygulamasını temsil eder. Personel (teller01) token'ını şube gateway'i üzerinden staff
# realm'inden alır (/sso/..., lab'de direct grant), 4 dakikada bir yeniler; her saniye cihaz sertifikası + token ile istek atar.
log "branch-terminal ($BRANCH_DEVICE, cihaz sertifikası: Branch CA)"
docker rm -f branch-terminal >/dev/null 2>&1 || true
docker run -d --name branch-terminal --restart unless-stopped --network "$BRANCH_NETWORK" \
  -e HOST="$BRANCH_HOST" -e STAFF_PW="$(cat "$ROOT_DIR/certs/data/kc-staff-teller01.pw" 2>/dev/null || true)" \
  -v "$ROOT_DIR/certs/branch/ca.pem:/ca.pem:ro" \
  -v "$ROOT_DIR/certs/branch/$BRANCH_DEVICE.crt:/device.crt:ro" \
  -v "$ROOT_DIR/certs/branch/$BRANCH_DEVICE.key:/device.key:ro" \
  --entrypoint /bin/sh "$LOADGEN_IMAGE" -c '
    req() { curl -s --cacert /ca.pem --cert /device.crt --key /device.key \
      --resolve "$HOST:443:$(getent hosts branch-fw | cut -d" " -f1)" "$@"; }
    i=0
    while true; do
      if [ $((i % 240)) -eq 0 ] || [ -z "$T" ]; then
        T=$(req "https://$HOST/sso/realms/staff/protocol/openid-connect/token" -d grant_type=password \
              -d client_id=branch-teller -d username=teller01 --data-urlencode "password=$STAFF_PW" \
            | sed -n "s/.*\"access_token\":\"\([^\"]*\)\".*/\1/p")
      fi
      i=$((i+1))
      req -o /dev/null -H "Authorization: Bearer $T" "https://$HOST/branch/v1/accounts"
      sleep 1
    done' >/dev/null

log "Şube kanalı hazır mı?"
for i in $(seq 1 30); do
  code=$(MSYS_NO_PATHCONV=1 docker exec branch-terminal sh -c \
    'curl -s -o /dev/null -w "%{http_code}" --max-time 5 --cacert /ca.pem --cert /device.crt --key /device.key \
       --resolve "$HOST:443:$(getent hosts branch-fw | cut -d" " -f1)" "https://$HOST/branch/v1/healthz"' || true)
  # Token'sız istek: 401 = mTLS, gateway ve ext_authz çalışıyor (08'den önce 200)
  [[ "$code" == "200" || "$code" == "401" ]] && { echo "  https://$BRANCH_HOST/branch/v1/ -> $code"; break; }
  [[ $i -eq 30 ]] && { echo "  şube kanalı yanıt vermedi (son kod: $code)"; exit 1; }
  sleep 2
done
