#!/usr/bin/env bash
# Secret yönetimi (13 · secrets): Vault (mgmt) + External Secrets Operator (her cluster) + parolaların Vault'a yazılması.
#   1. Vault'u kurar, başlatır (init), mührünü açar (unseal). Başlatma çıktısı certs/vault/init.json (gitignore'lu).
#   2. Yapılandırır: audit (stdout), KV v2 (kv/), cluster başına JWT auth (jwt-<cluster>), namespace başına politika + rol.
#   3. Her cluster'a External Secrets Operator kurar (yalnızca controller; webhook ve cert controller kapalı).
#   4. Parolaları üretir ya da Vault'taki değerleri korur (kv/ops/passwords) ve uygulama secret'larını
#      kv/<cluster>/<namespace>/<ad> yollarına yazar. Kubernetes Secret'larını External Secrets oluşturur (manifestler: 01-secrets.yaml).
#   Database motoru PostgreSQL ayağa kalktıktan sonra yapılandırılır (06a-vault-database.sh).
source "$(dirname "$0")/lib.sh"

M=(kubectl --context "$(ctx mgmt)")
mkdir -p "$(dirname "$VAULT_INIT")"

# Hangi namespace hangi secret'ları okuyabilir: <cluster>:<namespace>[:<database rolü>]
STORES="dmz:ratelimit dmz:auth dmz:edge-web cluster-a:api-a cluster-a:channel-bff cluster-a:account-api:account-api
  mgmt:data mgmt:iam:device-registry mgmt:istio-system mgmt:istio-ingress"

log "Vault -> mgmt"
apply_rendered "$(ctx mgmt)" "$ROOT_DIR/infra/vault/vault.yaml" >/dev/null
"${M[@]}" -n vault rollout status sts/vault --timeout=300s
for i in $(seq 1 30); do
  "${M[@]}" -n vault exec vault-0 -c vault -- vault status -format=json >/dev/null 2>&1 && break
  [[ $? -eq 2 ]] && break   # 2 = mühürlü: sunucu yanıt veriyor
  sleep 2
done
status() { "${M[@]}" -n vault exec vault-0 -c vault -- vault status -format=json 2>/dev/null || true; }
jget() { python -c "import json,sys; print(str(json.load(sys.stdin)[sys.argv[1]]).lower())" "$1" | tr -d '\r'; }

if [[ $(status | jget initialized) != true ]]; then
  echo "  başlatılıyor (init: 1 anahtar parçası; gerçekte 5 parça / 3 eşik ya da HSM ile otomatik unseal)"
  "${M[@]}" -n vault exec vault-0 -c vault -- vault operator init -key-shares=1 -key-threshold=1 -format=json > "$VAULT_INIT"
  chmod 600 "$VAULT_INIT"
fi
if [[ $(status | jget sealed) == true ]]; then
  echo "  mühür açılıyor (unseal)"
  key=$(python -c "import json,sys; print(json.load(open(sys.argv[1]))['unseal_keys_b64'][0])" "$VAULT_INIT" | tr -d '\r')
  "${M[@]}" -n vault exec vault-0 -c vault -- vault operator unseal "$key" >/dev/null
fi
for i in $(seq 1 30); do [[ $(status | jget sealed) == false ]] && break; sleep 2; done
echo "  Vault: başlatıldı, mühür açık"

log "Vault yapılandırması (audit, KV, JWT auth, politikalar)"
vault_cmd audit list -format=json 2>/dev/null | grep -q '"file/"' \
  || vault_cmd audit enable file file_path=stdout log_raw=false >/dev/null
vault_cmd secrets list -format=json | grep -q '"kv/"' || vault_cmd secrets enable -path=kv kv-v2 >/dev/null

# JWT auth: cluster başına ayrı mount. Vault cluster'ın API'sini çağırmaz; service account token'larının imza anahtarı
# (kube-apiserver'ın sa.pub'u) ve issuer sabit olarak yazılır. Bir cluster'ın token'ı başka cluster'ın mount'unda geçmez.
for c in $CLUSTERS; do
  vault_cmd auth list -format=json | grep -q "\"jwt-$c/\"" || vault_cmd auth enable -path="jwt-$c" jwt >/dev/null
  pub=$(docker exec "$c-control-plane" cat /etc/kubernetes/pki/sa.pub)
  iss=$(kubectl --context "$(ctx "$c")" -n default create token default --audience vault --duration 10m \
        | python -c "import base64,json,sys; p=sys.stdin.read().strip().split('.')[1]; print(json.loads(base64.urlsafe_b64decode(p + '=' * (-len(p) % 4)))['iss'])" | tr -d '\r')
  python -c "import json,sys; print(json.dumps({'jwt_validation_pubkeys': [sys.argv[1]], 'bound_issuer': sys.argv[2]}))" "$pub" "$iss" \
    | vault_cmd write "auth/jwt-$c/config" - >/dev/null
  echo "  jwt-$c: issuer $iss"
done

# Namespace başına: yalnızca kendi KV yolunu (ve varsa kendi veritabanı rolünü) okuyan politika; rol yalnızca o
# namespace'in vault-reader service account'unun token'ını kabul eder (audience vault).
for s in $STORES; do
  IFS=: read -r c ns db <<<"$s"
  {
    printf 'path "kv/data/%s/%s/*" {\n  capabilities = ["read"]\n}\n' "$c" "$ns"
    if [[ -n ${db:-} ]]; then printf 'path "database/creds/%s" {\n  capabilities = ["read"]\n}\n' "$db"; fi
  } | vault_cmd policy write "$c-$ns" - >/dev/null
  # Token: 10 dk, External Secrets işi bitince iptal eder. Veritabanı kullanıcısı okuyan rollerde batch token: Vault bir
  # token iptal edilince onunla alınan kiraları (lease) da iptal eder; servis token'ıyla alınan kullanıcı ESO token'ını
  # bıraktığı anda silinirdi. Batch token'ın kiraları token'a bağlı değildir, kendi ömürleriyle (DB_CREDS_TTL) yaşar;
  # bunun için token ömrü kullanıcı ömründen uzun olmalı (2 sa > 1 sa). Batch token iptal edilemez, ömrü dolunca biter.
  tok=(token_type=service token_ttl=10m token_max_ttl=10m)
  [[ -n ${db:-} ]] && tok=(token_type=batch token_ttl=2h token_max_ttl=2h)
  vault_cmd write "auth/jwt-$c/role/$ns" role_type=jwt bound_audiences=vault user_claim=sub \
    bound_subject="system:serviceaccount:$ns:vault-reader" token_policies="$c-$ns" "${tok[@]}" >/dev/null
  echo "  $c/$ns: politika $c-$ns${db:+ (+ database/creds/$db)}"
done

log "External Secrets Operator"
helm repo add external-secrets https://charts.external-secrets.io --force-update >/dev/null
vals=$(mktemp)
cat > "$vals" <<EOF
installCRDs: true
image:
  repository: $LAB_REGISTRY/lab/external-secrets   # 03b-publish-images.sh (LAB_PULLS)
  tag: v2.13.0
# Yalnızca controller: webhook ve sertifika controller'ı kapalı (bellek; API sunucusu -> webhook çağrısı mesh'in STRICT
# mTLS'ine takılırdı). Kaynakların doğrulaması CRD şemasıyla yapılır.
webhook:
  create: false
certController:
  create: false
concurrent: 1
# Yalnızca namespace'e bağlı kaynaklar (SecretStore, ExternalSecret, üreteçler). Cluster genelindeki türler kurulmaz ve
# izlenmez: hem en az yetki (bir namespace başka namespace'in store'unu kullanamaz) hem bellek (ClusterSecretStore
# CRD'si tek başına ~0,7 MB şema; API sunucusu her CRD'nin şemasını bellekte tutar).
crds:
  createClusterExternalSecret: false
  createClusterSecretStore: false
  createClusterGenerator: false
  createClusterPushSecret: false
  createPushSecret: false
processClusterExternalSecret: false
processClusterStore: false
processClusterGenerator: false
processClusterPushSecret: false
processPushSecret: false
resources:
  requests:
    cpu: 10m
    memory: 64Mi
  limits:
    memory: 256Mi
EOF
for c in $CLUSTERS; do
  zone=$(case $c in dmz) echo dmz ;; mgmt) echo mgmt ;; *) echo internal ;; esac)
  kubectl --context "$(ctx "$c")" apply -f - >/dev/null <<EOF
apiVersion: v1
kind: Namespace
metadata:
  name: external-secrets
  labels:
    zone: $zone
    istio.io/dataplane-mode: ambient
$([[ $c != mgmt ]] && echo '    istio.io/use-waypoint: waypoint   # Vault çıkışı waypoint üzerinden (64-vault-exit.yaml)')
    policy.corp.mesh/image-source: lab-registry
    pod-security.kubernetes.io/enforce: restricted
EOF
  helm upgrade --install external-secrets external-secrets/external-secrets --kube-context "$(ctx "$c")" \
    -n external-secrets --version "$ESO_CHART_VERSION" -f "$(cygpath -m "$vals")" --wait --timeout 300s >/dev/null
  echo "  $c: external-secrets"
done
rm -f "$vals"

log "Parolalar ve uygulama secret'ları -> Vault"
pwf_load
# Önceki sürümün düz dosyaları varsa (certs/data/*.pw) değerler bir kez Vault'a taşınır, sonra dosyalar silinir.
if [[ -d $ROOT_DIR/certs/data ]]; then
  for f in "$ROOT_DIR"/certs/data/*.pw; do
    [[ -f $f ]] || continue
    n=$(basename "$f" .pw); [[ -n ${_PWF[$n]:-} ]] || _PWF[$n]=$(tr -d '\r\n' < "$f")
  done
fi
NAMES="postgres-admin pg-keycloak pg-vault-admin valkey-admin valkey-api-a valkey-ratelimit valkey-web-session valkey-dpop
  keycloak-admin kc-web-app kc-auth-web kc-auth-mobile kc-auth-partner kc-auth-branch kc-customer-ayse kc-customer-ayse-otp
  kc-customer-mehmet kc-customer-mehmet-otp kc-staff-teller01 kc-staff-yetkili01 kc-staff-yetkili02 kc-partner-acme
  kc-partner-initech grafana-admin grafana-dev01 grafana-netops01 grafana-soc01 grafana-dba01 grafana-platform01"
for n in $NAMES; do [[ -n ${_PWF[$n]:-} ]] || _PWF[$n]=$(openssl rand -hex 16); done
p() { echo "${_PWF[$1]}"; }

# kvput <yol> <anahtar=değer | anahtar=@dosya>...: JSON'u Python kurar (değerler satır sonu / özel karakter içerebilir)
kvput() {
  local path=$1; shift
  python -c "
import json, sys
d = {}
for a in sys.argv[1:]:
    k, v = a.split('=', 1)
    d[k] = open(v[1:], encoding='utf-8').read() if v.startswith('@') else v
sys.stdout.buffer.write(json.dumps(d).encode())" "$@" | vault_cmd kv put -mount=kv "$path" - >/dev/null
  echo "  kv/$path"
}
kvput ops/passwords $(for n in "${!_PWF[@]}"; do printf '%s=%s ' "$n" "${_PWF[$n]}"; done)

kvput mgmt/data/postgres-admin POSTGRES_PASSWORD="$(p postgres-admin)"
kvput mgmt/data/postgres-app-users KEYCLOAK_DB_PASSWORD="$(p pg-keycloak)" VAULT_ADMIN_PASSWORD="$(p pg-vault-admin)"
acl="user default off
user admin on >$(p valkey-admin) ~* &* +@all
user api_a on >$(p valkey-api-a) ~cache:api-a:* ~api-a-* resetchannels -@all +@read +@write +@keyspace +ping +hello +auth -@dangerous
user ratelimit on >$(p valkey-ratelimit) ~rl:* resetchannels -@all +@read +@write +@keyspace +@transaction +ping +hello +auth -@dangerous
user web_session on >$(p valkey-web-session) ~sess:* resetchannels -@all +get +set +del +ping +hello +auth
user dpop on >$(p valkey-dpop) ~dpop:* resetchannels -@all +set +ping +hello +auth"
kvput mgmt/data/valkey-acl "users.acl=$acl"
kvput cluster-a/api-a/api-a-cache PODINFO_CACHE_SERVER="redis://api_a:$(p valkey-api-a)@valkey.api-a.svc.cluster.local:6379"
kvput dmz/ratelimit/ratelimit-redis REDIS_AUTH="ratelimit:$(p valkey-ratelimit)"
kvput mgmt/iam/keycloak-db KC_DB_PASSWORD="$(p pg-keycloak)"
kvput mgmt/iam/keycloak-admin KC_BOOTSTRAP_ADMIN_USERNAME=admin KC_BOOTSTRAP_ADMIN_PASSWORD="$(p keycloak-admin)"

# Keycloak realm'leri: client secret'ları, test kullanıcılarının parolaları ve IdP imza anahtarı yerleştirilmiş JSON
pem_body() { grep -v -- '-----' "$1" | tr -d '\r\n'; }
tmp=$(mktemp -d)
realms=()
for f in "$ROOT_DIR"/infra/keycloak/realm-*.json; do
  realm=$(basename "$f" .json); realm=${realm#realm-}
  sed -e "s|__LAB_DIRECT_GRANT__|true|g" \
      -e "s|__IDP_PRIVATE_KEY__|$(pem_body "$ROOT_DIR/certs/idp/$realm.key")|g" \
      -e "s|__IDP_CERTIFICATE__|$(pem_body "$ROOT_DIR/certs/idp/$realm.crt")|g" \
      -e "s|__WEB_APP_SECRET__|$(p kc-web-app)|g" \
      -e "s|__AUTH_WEB_SECRET__|$(p kc-auth-web)|g" \
      -e "s|__AUTH_MOBILE_SECRET__|$(p kc-auth-mobile)|g" \
      -e "s|__AUTH_PARTNER_SECRET__|$(p kc-auth-partner)|g" \
      -e "s|__AUTH_BRANCH_SECRET__|$(p kc-auth-branch)|g" \
      -e "s|__CUSTOMER_PASSWORD__|$(p kc-customer-ayse)|g" \
      -e "s|__CUSTOMER_OTP_SECRET__|$(p kc-customer-ayse-otp)|g" \
      -e "s|__CUSTOMER2_PASSWORD__|$(p kc-customer-mehmet)|g" \
      -e "s|__CUSTOMER2_OTP_SECRET__|$(p kc-customer-mehmet-otp)|g" \
      -e "s|__STAFF_PASSWORD__|$(p kc-staff-teller01)|g" \
      -e "s|__STAFF_SUP1_PASSWORD__|$(p kc-staff-yetkili01)|g" \
      -e "s|__STAFF_SUP2_PASSWORD__|$(p kc-staff-yetkili02)|g" \
      -e "s|__PARTNER_ACME_SECRET__|$(p kc-partner-acme)|g" \
      -e "s|__PARTNER_INITECH_SECRET__|$(p kc-partner-initech)|g" \
      "$f" > "$tmp/$(basename "$f")"
  realms+=("$(basename "$f")=@$(cd "$tmp" && (pwd -W 2>/dev/null || pwd))/$(basename "$f")")
done
kvput mgmt/iam/keycloak-realms "${realms[@]}"
rm -rf "$tmp"

kvput dmz/auth/auth-exchange-clients AUTH_WEB_SECRET="$(p kc-auth-web)" AUTH_MOBILE_SECRET="$(p kc-auth-mobile)" \
  AUTH_PARTNER_SECRET="$(p kc-auth-partner)" AUTH_BRANCH_SECRET="$(p kc-auth-branch)"
kvput dmz/auth/auth-dpop-store VALKEY_USER=dpop VALKEY_PASSWORD="$(p valkey-dpop)"
kvput dmz/auth/attest-public "attest.pub=@$ROOT_DIR/certs/attest/attest.pub"
kvput cluster-a/channel-bff/attest-public "attest.pub=@$ROOT_DIR/certs/attest/attest.pub"
kvput dmz/edge-web/web-token-handler CLIENT_SECRET="$(p kc-web-app)" VALKEY_USER=web_session VALKEY_PASSWORD="$(p valkey-web-session)"
kvput mgmt/istio-system/grafana-admin GF_SECURITY_ADMIN_USER=admin GF_SECURITY_ADMIN_PASSWORD="$(p grafana-admin)" \
  password="$(p grafana-admin)"
kvput mgmt/istio-ingress/logs-edge-mtls "tls.crt=@$ROOT_DIR/certs/logs/server.crt" "tls.key=@$ROOT_DIR/certs/logs/server.key" \
  "ca.crt=@$ROOT_DIR/certs/logs/ca.pem"

if [[ -d $ROOT_DIR/certs/data ]]; then
  rm -rf "$ROOT_DIR/certs/data"
  echo "  eski düz parola dosyaları (certs/data/) silindi: değerler Vault'ta (kv/ops/passwords)"
fi
