#!/usr/bin/env bash
# Veri katmanının ve kimlik altyapısının (08) kimlik bilgileri: servis başına ayrı kullanıcı ve parola.
# Parolalar bir kez üretilir (certs/data/, git'e girmez) ve yalnızca kullanan cluster/namespace'e Secret olarak yazılır.
# Gerçekte Vault'ta durur ve dinamik (kısa ömürlü) üretilir: 13 · secrets.
source "$(dirname "$0")/lib.sh"

DIR="$ROOT_DIR/certs/data"
mkdir -p "$DIR"
pw() {  # pw <ad>: yoksa üret, varsa oku
  [[ -f "$DIR/$1.pw" ]] || openssl rand -hex 16 > "$DIR/$1.pw"
  cat "$DIR/$1.pw"
}
secret() {  # secret <cluster> <namespace> <ad> <kubectl create secret generic argümanları...>
  local c=$1 ns=$2 name=$3; shift 3
  kubectl --context "$(ctx "$c")" -n "$ns" create secret generic "$name" "$@" --dry-run=client -o yaml \
    | kubectl --context "$(ctx "$c")" apply -f - >/dev/null
  echo "  $c/$ns/$name"
}

log "Veri secret'ları"
# mgmt: PostgreSQL yöneticisi ve uygulama kullanıcıları (init betiği rolleri bu parolalarla oluşturur)
secret mgmt data postgres-admin --from-literal=POSTGRES_PASSWORD="$(pw postgres-admin)"
secret mgmt data postgres-app-users --from-literal=ACCOUNT_API_PASSWORD="$(pw pg-account-api)" \
  --from-literal=KEYCLOAK_DB_PASSWORD="$(pw pg-keycloak)"

# mgmt: Valkey ACL. default kullanıcı kapalı; her istemci yalnızca kendi anahtar önekinde, tehlikeli komutlar yok
acl=$(cat <<EOF
user default off
user admin on >$(pw valkey-admin) ~* &* +@all
user api_a on >$(pw valkey-api-a) ~cache:api-a:* ~api-a-* resetchannels -@all +@read +@write +@keyspace +ping +hello +auth -@dangerous
user ratelimit on >$(pw valkey-ratelimit) ~rl:* resetchannels -@all +@read +@write +@keyspace +@transaction +ping +hello +auth -@dangerous
user web_session on >$(pw valkey-web-session) ~sess:* resetchannels -@all +get +set +del +ping +hello +auth
EOF
)
secret mgmt data valkey-acl --from-literal=users.acl="$acl"

# cluster-a: account-api -> PostgreSQL (libpq ortam değişkenleri; yalnızca kendi kullanıcısı)
secret cluster-a account-api account-api-db \
  --from-literal=PGUSER=account_api --from-literal=PGPASSWORD="$(pw pg-account-api)"
# cluster-a: api-a (podinfo) önbelleği -> Valkey (api_a kullanıcısı)
secret cluster-a api-a api-a-cache \
  --from-literal=PODINFO_CACHE_SERVER="redis://api_a:$(pw valkey-api-a)@valkey.api-a.svc.cluster.local:6379"
# dmz: global rate limit servisi -> Valkey (ratelimit kullanıcısı)
secret dmz ratelimit ratelimit-redis --from-literal=REDIS_AUTH="ratelimit:$(pw valkey-ratelimit)"

# --- Kimlik (08 · token-exchange) ---
# mgmt: Keycloak'ın veritabanı ve ilk yönetici hesabı
secret mgmt iam keycloak-db --from-literal=KC_DB_PASSWORD="$(pw pg-keycloak)"
secret mgmt iam keycloak-admin --from-literal=KC_BOOTSTRAP_ADMIN_USERNAME=admin \
  --from-literal=KC_BOOTSTRAP_ADMIN_PASSWORD="$(pw keycloak-admin)"

# mgmt: realm'ler (client secret'ları, test kullanıcı parolaları ve realm imza anahtarıyla). Direct grant (ROPC) yalnızca
# lab testleri için (mobil, personel); web'de yok: web-app gizli client, giriş tarayıcıda Authorization Code + PKCE ile.
pem_body() { grep -v -- '-----' "$1" | tr -d '\r\n'; }   # PEM -> tek satır base64 (realm JSON'undaki key provider'a)
tmp=$(cd "$(mktemp -d)" && (pwd -W 2>/dev/null || pwd))   # Windows kubectl için C:/... biçimi
for f in "$ROOT_DIR"/infra/keycloak/realm-*.json; do
  realm=$(basename "$f" .json); realm=${realm#realm-}
  sed -e "s|__LAB_DIRECT_GRANT__|true|g" \
      -e "s|__IDP_PRIVATE_KEY__|$(pem_body "$ROOT_DIR/certs/idp/$realm.key")|g" \
      -e "s|__IDP_CERTIFICATE__|$(pem_body "$ROOT_DIR/certs/idp/$realm.crt")|g" \
      -e "s|__WEB_APP_SECRET__|$(pw kc-web-app)|g" \
      -e "s|__AUTH_WEB_SECRET__|$(pw kc-auth-web)|g" \
      -e "s|__AUTH_MOBILE_SECRET__|$(pw kc-auth-mobile)|g" \
      -e "s|__AUTH_PARTNER_SECRET__|$(pw kc-auth-partner)|g" \
      -e "s|__AUTH_BRANCH_SECRET__|$(pw kc-auth-branch)|g" \
      -e "s|__CUSTOMER_PASSWORD__|$(pw kc-customer-ayse)|g" \
      -e "s|__CUSTOMER_OTP_SECRET__|$(pw kc-customer-ayse-otp)|g" \
      -e "s|__STAFF_PASSWORD__|$(pw kc-staff-teller01)|g" \
      -e "s|__PARTNER_ACME_SECRET__|$(pw kc-partner-acme)|g" \
      -e "s|__PARTNER_INITECH_SECRET__|$(pw kc-partner-initech)|g" \
      "$f" > "$tmp/$(basename "$f")"
done
secret mgmt iam keycloak-realms $(for f in "$tmp"/*.json; do printf -- '--from-file=%s ' "$f"; done)
rm -rf "$tmp"

# --- Token exchange ve web oturumu (09a · idp-token-exchange) ---
# dmz: auth-service'in kanal başına exchange client'ları (iç JWT'yi Keycloak imzalar; DMZ'de imza anahtarı yok)
secret dmz auth auth-exchange-clients --from-literal=AUTH_WEB_SECRET="$(pw kc-auth-web)" \
  --from-literal=AUTH_MOBILE_SECRET="$(pw kc-auth-mobile)" --from-literal=AUTH_PARTNER_SECRET="$(pw kc-auth-partner)" \
  --from-literal=AUTH_BRANCH_SECRET="$(pw kc-auth-branch)"
# dmz: web-token-handler -> Keycloak (web-app gizli client'ı) ve oturum deposu (mgmt Valkey, web_session kullanıcısı)
secret dmz edge-web web-token-handler --from-literal=CLIENT_SECRET="$(pw kc-web-app)" \
  --from-literal=VALKEY_USER=web_session --from-literal=VALKEY_PASSWORD="$(pw valkey-web-session)"

