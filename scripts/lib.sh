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

start_registry_caches() {
  local entry reg url name
  for entry in $REGISTRY_MIRRORS; do
    reg=${entry%%=*} url=${entry#*=} name=$(cache_name "$reg")
    if [[ -z "$(docker ps -q --filter "name=^${name}$")" ]]; then
      docker rm -f "$name" >/dev/null 2>&1 || true
      docker run -d --restart=always --name "$name" --network kind \
        -v "${name}:/var/lib/registry" \
        -e REGISTRY_PROXY_REMOTEURL="$url" \
        "$REGISTRY_IMAGE" >/dev/null
      echo "  başlatıldı: $name -> $url"
    else
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
    docker run -d --restart=always --name "$name" --network kind \
      -p "127.0.0.1:${LAB_REGISTRY_HOST_PORT}:5000" \
      -v "${name}:/var/lib/registry" "$REGISTRY_IMAGE" >/dev/null
    echo "  başlatıldı: $name"
  else
    echo "  çalışıyor: $name"
  fi
}

# Node'daki containerd'ye her registry için önbelleği mirror olarak tanıtır.
# Önbellek erişilemezse containerd asıl registry'ye (server) düşer.
configure_node_mirrors() {
  local cluster=$1 node entry reg url
  for node in $(kind get nodes --name "$cluster"); do
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
#   __INTERNAL_JWKS__ -> iç JWT'yi doğrulayan açık anahtar (certs/auth/jwks.json; 08 · token-exchange)
apply_rendered() {
  local context=$1 path=$2 jwks=""
  [[ -f "$ROOT_DIR/certs/auth/jwks.json" ]] && jwks=$(cat "$ROOT_DIR/certs/auth/jwks.json")
  sed -e "s/__NET_PREFIX__/$(detect_net_prefix)/g" -e "s|__INTERNAL_JWKS__|$jwks|g" "$path"     | kubectl --context "$context" apply -f -
}
