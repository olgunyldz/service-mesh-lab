#!/usr/bin/env bash
# Ortak yardımcılar - diğer scriptler source eder.
set -euo pipefail

# Git Bash'te `pwd -W` C:/... biçimi verir; Windows exe'leri (kind, kubectl) bunu anlar
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && (pwd -W 2>/dev/null || pwd))"
# shellcheck source=../config.env
source "$ROOT_DIR/config.env"

# Git Bash'te openssl -subj "/O=..." gibi argümanların Windows path'ine çevrilmesini engelle
export MSYS_NO_PATHCONV=1

log() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }

# Cluster aktif mi? (CLUSTERS listesinde mi)
has_cluster() { [[ " $CLUSTERS " == *" $1 "* ]]; }

# Internal cluster'lar (dmz dışındakiler)
internal_clusters() {
  local c
  for c in $CLUSTERS; do [[ $c == dmz ]] || echo "$c"; done
}

# URL'nin HTTP durum kodunu yazar. Git Bash'teki curl Windows programı olduğu için
# MSYS_NO_PATHCONV açıkken /dev/null'a yazamıyor (exit 23); bu çağrıda kapatılır.
http_code() {
  env -u MSYS_NO_PATHCONV curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$1" || true
}

detect_net_prefix() {
  if [[ -z "${NET_PREFIX:-}" ]]; then
    local subnet
    subnet=$(docker network inspect kind -f '{{range .IPAM.Config}}{{.Subnet}} {{end}}' | tr ' ' '\n' | grep -E '^[0-9]+\.' | head -1)
    NET_PREFIX=$(echo "$subnet" | cut -d. -f1-2)
  fi
  echo "$NET_PREFIX"
}

# --- Registry önbelleği (pull-through cache) ---------------------------------
# Her cluster'ın aynı image'ı internetten ayrı ayrı (ve her sıfırlamada yeniden) çekmesini önler.
# Önbellek container'ları cluster'lardan bağımsızdır; 99-destroy.sh onları silmez.

cache_name() { echo "cache-${1//./-}"; }   # docker.io -> cache-docker-io

# Registry ağı (13 · secrets ile gelen sertleştirme): registry'ler kind ağında değil. Eski kurulumdan kalan container
# kind ağına bağlıysa oradan çıkarılır.
registry_network() {
  docker network inspect "$REGISTRY_NETWORK" >/dev/null 2>&1 || docker network create "$REGISTRY_NETWORK" >/dev/null
}
use_registry_network() {  # use_registry_network <container>
  docker network connect "$REGISTRY_NETWORK" "$1" >/dev/null 2>&1 || true
  # kind'dan çıkarılınca yayınlanan port (lab registry: 127.0.0.1:5001) düşer; yeniden başlatınca yeni ağda geri gelir
  if docker network disconnect kind "$1" >/dev/null 2>&1; then docker restart "$1" >/dev/null; fi
}

start_registry_caches() {
  local entry reg url name
  for entry in $REGISTRY_MIRRORS; do
    reg=${entry%%=*} url=${entry#*=} name=$(cache_name "$reg")
    if [[ -z "$(docker ps -q --filter "name=^${name}$")" ]]; then
      docker rm -f "$name" >/dev/null 2>&1 || true
      docker run -d --restart=always --name "$name" --network "$REGISTRY_NETWORK" \
        -v "${name}:/var/lib/registry" \
        -e REGISTRY_PROXY_REMOTEURL="$url" \
        "$REGISTRY_IMAGE" >/dev/null
      echo "  başlatıldı: $name -> $url"
    else
      use_registry_network "$name"
      echo "  çalışıyor: $name"
    fi
  done
}

# İmzalı uygulama image'larının tutulduğu iç registry (önbellek değil, asıl kaynak)
# Host'a yalnızca 127.0.0.1'den açılır: kendi servislerimizin image'ları host'ta build edilip buraya itilir.
start_lab_registry() {
  local name=${LAB_REGISTRY%%:*}
  # Port yayını olmayan eski container (05 · policy) yeniden oluşturulur; veri volume'da kalır
  if [[ -n "$(docker ps -q --filter "name=^${name}$")" && -z "$(docker port "$name" 5000 2>/dev/null)" ]]; then
    docker rm -f "$name" >/dev/null
  fi
  if [[ -z "$(docker ps -q --filter "name=^${name}$")" ]]; then
    docker rm -f "$name" >/dev/null 2>&1 || true
    docker run -d --restart=always --name "$name" --network "$REGISTRY_NETWORK" \
      -p "127.0.0.1:${LAB_REGISTRY_HOST_PORT}:5000" \
      -v "${name}:/var/lib/registry" "$REGISTRY_IMAGE" >/dev/null
    echo "  başlatıldı: $name"
  else
    use_registry_network "$name"
    echo "  çalışıyor: $name"
  fi
}

# Node'daki containerd'ye her registry için önbelleği mirror olarak tanıtır. Node registry ağına da bağlanır.
# Önbellek erişilemezse containerd asıl registry'ye (server) düşer.
configure_node_mirrors() {
  local cluster=$1 node entry reg url
  for node in $(kind get nodes --name "$cluster"); do
    docker network connect "$REGISTRY_NETWORK" "$node" >/dev/null 2>&1 || true
    for entry in $REGISTRY_MIRRORS; do
      reg=${entry%%=*} url=${entry#*=}
      # -i şart: yoksa heredoc container'a aktarılmaz ve hosts.toml boş kalır
      docker exec -i "$node" sh -c "mkdir -p /etc/containerd/certs.d/$reg && cat > /etc/containerd/certs.d/$reg/hosts.toml" <<EOF
server = "$url"

[host."http://$(cache_name "$reg"):5000"]
  capabilities = ["pull", "resolve"]
EOF
    done
    # Lab registry düz HTTP (lab istisnası); containerd'ye bunu söylemek gerekir
    docker exec -i "$node" sh -c "mkdir -p /etc/containerd/certs.d/$LAB_REGISTRY && cat > /etc/containerd/certs.d/$LAB_REGISTRY/hosts.toml" <<EOF
server = "http://$LAB_REGISTRY"

[host."http://$LAB_REGISTRY"]
  capabilities = ["pull", "resolve"]
EOF
  done
}

# Manifest içindeki yer tutucuları doldurup uygular:
#   __NET_PREFIX__   -> kind ağının ilk iki okteti
#   __IDP_JWKS_<realm>__ -> iç JWT'yi doğrulayan realm açık anahtarı (certs/idp/<realm>.jwks.json; 09a)
apply_rendered() {
  local context=$1 path=$2 args=() f
  for f in "$ROOT_DIR"/certs/idp/*.jwks.json; do
    [[ -f $f ]] && args+=(-e "s|__IDP_JWKS_$(basename "$f" .jwks.json)__|$(cat "$f")|g")
  done
  sed -e "s/__NET_PREFIX__/$(detect_net_prefix)/g" "${args[@]}" "$path" | kubectl --context "$context" apply -f -
}

# --- Vault (13 · secrets) ---
# Başlatma çıktısı (unseal anahtarı + root token): yalnızca bu makinede, gitignore'lu certs/vault/. Lab istisnası; gerçekte
# unseal HSM / KMS ile otomatik, root token kurulumdan sonra iptal edilir.
VAULT_INIT="$ROOT_DIR/certs/vault/init.json"
vault_root_token() { python -c "import json,sys; print(json.load(open(sys.argv[1]))['root_token'])" "$VAULT_INIT" | tr -d '\r'; }
vault_cmd() {  # vault_cmd <vault CLI argümanları...>: mgmt'teki Vault pod'unda, root token ile (stdin aktarılır)
  kubectl --context "$(ctx mgmt)" -n vault exec -i vault-0 -c vault -- env VAULT_TOKEN="$(vault_root_token)" vault "$@"
}

# Parolalar Vault'ta (kv/ops/passwords): diskte düz parola yok. pwf_load bir kez okur (tek exec), pwf <ad> döndürür.
# Script'in başında pwf_load çağrılmazsa her $(pwf ...) alt kabukta yeniden okur (yavaş ama doğru).
declare -gA _PWF=()
pwf_load() {
  local k v
  while IFS=$'\t' read -r k v; do [[ -n $k ]] && _PWF[$k]=${v%$'\r'}; done < <(
    vault_cmd kv get -format=json -mount=kv ops/passwords 2>/dev/null \
      | python -c "import json,sys; s=sys.stdin.read(); [print(k + '\t' + v) for k, v in (json.loads(s)['data']['data'] if s.strip() else {}).items()]" || true)
}
pwf() { (( ${#_PWF[@]} )) || pwf_load; echo "${_PWF[$1]:-}"; }

# --- Node koruması (kind ağı) ---
# kind ağı düz bir Docker ağı: cluster'lara köprü olan edge container'ları (edge-waf, branch-fw, edge-logs) node'ların
# kendi adreslerindeki API sunucusuna (6443), kubelet'e (10250) ve NodePort'lara (Grafana, Kiali, Keycloak yönetimi)
# ulaşabiliyordu. Her node'da bu portlara yalnızca host (Docker ağ geçidi: yayınlanan portlar buradan gelir), diğer
# node'lar ve node'un kendi pod'ları girebilir. Gateway VIP'leri (MetalLB) node adresi değildir, etkilenmez.
# Kural raw tablosunda: kube-proxy'nin NodePort yönlendirmesinden (nat) önce. Node container'ı yeniden başlarsa kural
# kaybolur; 08-verify.sh denetler, guard_nodes yeniden uygular.
guard_nodes() {
  local gw nodes n ip pod
  gw=$(docker network inspect kind -f '{{range .IPAM.Config}}{{.Gateway}} {{end}}' | tr ' ' '\n' | grep -E '^[0-9]+\.' | head -1)
  nodes=$(for c in $CLUSTERS; do for n in $(kind get nodes --name "$c"); do
    docker inspect -f '{{.NetworkSettings.Networks.kind.IPAddress}}' "$n"; done; done | tr -d '
' | tr '
' ' ')
  for c in $CLUSTERS; do
    for n in $(kind get nodes --name "$c"); do
      ip=$(docker inspect -f '{{.NetworkSettings.Networks.kind.IPAddress}}' "$n")
      pod=$(kubectl --context "$(ctx "$c")" get node "$n" -o jsonpath='{.spec.podCIDR}' 2>/dev/null || true)
      docker exec -i "$n" sh -s <<EOF
iptables -t raw -N LAB-NODE-GUARD 2>/dev/null || iptables -t raw -F LAB-NODE-GUARD
for s in $gw $nodes $pod; do iptables -t raw -A LAB-NODE-GUARD -s \$s -j RETURN; done
iptables -t raw -A LAB-NODE-GUARD -j DROP
for p in 6443 10250 30000:32767; do
  iptables -t raw -C PREROUTING -d $ip -p tcp --dport \$p -j LAB-NODE-GUARD 2>/dev/null \
    || iptables -t raw -A PREROUTING -d $ip -p tcp --dport \$p -j LAB-NODE-GUARD
done
EOF
      echo "  $n: yalnızca host ($gw), node'lar ve pod'lar ($pod)"
    done
  done
}
