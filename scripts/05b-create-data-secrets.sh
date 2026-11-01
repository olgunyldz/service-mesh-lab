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

# mgmt: realm'ler (client secret'ları ve test kullanıcı parolalarıyla). Direct grant (ROPC) yalnızca lab testleri için.
tmp=$(cd "$(mktemp -d)" && (pwd -W 2>/dev/null || pwd))   # Windows kubectl için C:/... biçimi
for f in "$ROOT_DIR"/infra/keycloak/realm-*.json; do
  sed -e "s|__LAB_DIRECT_GRANT__|true|g" \
      -e "s|__CUSTOMER_PASSWORD__|$(pw kc-customer-ayse)|g" \
      -e "s|__STAFF_PASSWORD__|$(pw kc-staff-teller01)|g" \
      -e "s|__PARTNER_ACME_SECRET__|$(pw kc-partner-acme)|g" \
      -e "s|__PARTNER_INITECH_SECRET__|$(pw kc-partner-initech)|g" \
      "$f" > "$tmp/$(basename "$f")"
done
secret mgmt iam keycloak-realms $(for f in "$tmp"/*.json; do printf -- '--from-file=%s ' "$f"; done)
rm -rf "$tmp"

# dmz: iç JWT imza anahtarı (yalnızca auth-service; internal cluster'lar yalnızca açık anahtarı bilir)
secret dmz auth auth-signing-key --from-file=signing.key="$ROOT_DIR/certs/auth/signing.key"

