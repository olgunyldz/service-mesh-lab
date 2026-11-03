#!/usr/bin/env bash
# Vault Database motoru (13 · secrets): servis başına kısa ömürlü PostgreSQL kullanıcıları. PostgreSQL ayağa kalktıktan
# sonra çalışır (06-deploy-manifests.sh'ten sonra).
#   - Vault, PostgreSQL'e vault_admin ile bağlanır (CREATEROLE; account_api ve device_registry rollerini yalnızca
#     üyelik verebilecek kadar: ADMIN, INHERIT FALSE, SET FALSE). Bağlantıdan sonra parolası döndürülür (rotate-root):
#     o andan itibaren yalnızca Vault bilir.
#   - account_api ve device_registry giriş yapamayan (NOLOGIN) rollerdir; yetkiler onlarda. Vault her istekte bu rolün
#     üyesi yeni bir kullanıcı üretir (DB_CREDS_TTL), süre dolunca (ya da iptal edilince) açık oturumlarını kapatır ve
#     kullanıcıyı siler. Oturum kapatma için vault_admin'de pg_signal_backend var (20-data.yaml).
#   - Kullanıcının oturum rolü sahip rol olarak ayarlanır (SET role): oluşturduğu tablo vb. kullanıcıya değil role ait olur,
#     kullanıcı silinince nesneler kalır.
source "$(dirname "$0")/lib.sh"

log "Vault Database motoru (PostgreSQL)"
kubectl --context "$(ctx mgmt)" -n data rollout status sts/postgres --timeout=300s >/dev/null
vault_cmd secrets list -format=json | grep -q '"database/"' || vault_cmd secrets enable database >/dev/null

if ! vault_cmd read database/config/postgres >/dev/null 2>&1; then
  pwf_load
  for i in $(seq 1 30); do   # PostgreSQL ilk açılışta init betiğini çalıştırırken bağlantı reddedilebilir
    vault_cmd write database/config/postgres plugin_name=postgresql-database-plugin \
      connection_url="postgresql://{{username}}:{{password}}@postgres.data.svc.cluster.local:5432/corebank?sslmode=disable" \
      allowed_roles="account-api,device-registry" username=vault_admin password="$(pwf pg-vault-admin)" \
      password_authentication=scram-sha-256 >/dev/null 2>&1 && break
    sleep 5
  done
  vault_cmd read database/config/postgres >/dev/null
  vault_cmd write -f database/rotate-root/postgres >/dev/null
  echo "  bağlantı kuruldu; vault_admin parolası döndürüldü (yalnızca Vault biliyor)"
fi

role() {  # role <vault rolü> <sahip PostgreSQL rolü>
  vault_cmd write "database/roles/$1" db_name=postgres default_ttl="$DB_CREDS_TTL" max_ttl=4h \
    creation_statements="CREATE ROLE \"{{name}}\" WITH LOGIN PASSWORD '{{password}}' VALID UNTIL '{{expiration}}' CONNECTION LIMIT 10 IN ROLE $2; ALTER ROLE \"{{name}}\" SET role TO '$2';" \
    revocation_statements="SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE usename = '{{name}}'; DROP ROLE IF EXISTS \"{{name}}\";" >/dev/null
  echo "  database/roles/$1: $2 üyesi, ömür $DB_CREDS_TTL"
}
role account-api account_api
role device-registry device_registry

# api-a (podinfo) önbelleğe (mgmt Valkey) yalnızca açılışta bağlanır, bağlanamazsa "offline" kalır. Secret'lar External
# Secrets ile geldiği için api-a, Valkey'den önce açılabiliyor: Valkey hazır olunca api-a bir kez yeniden başlatılır.
kubectl --context "$(ctx mgmt)" -n data rollout status deploy/valkey --timeout=300s >/dev/null
kubectl --context "$(ctx cluster-a)" -n api-a rollout restart deploy/api-a >/dev/null
kubectl --context "$(ctx cluster-a)" -n api-a rollout status deploy/api-a --timeout=180s >/dev/null
echo "  api-a yeniden başlatıldı (Valkey hazır)"
