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

detect_net_prefix() {
  if [[ -z "${NET_PREFIX:-}" ]]; then
    local subnet
    subnet=$(docker network inspect kind -f '{{range .IPAM.Config}}{{.Subnet}} {{end}}' | tr ' ' '\n' | grep -E '^[0-9]+\.' | head -1)
    NET_PREFIX=$(echo "$subnet" | cut -d. -f1-2)
  fi
  echo "$NET_PREFIX"
}

# Manifest içindeki __NET_PREFIX__ yer tutucusunu doldurup uygular
apply_rendered() {
  local context=$1 path=$2
  sed "s/__NET_PREFIX__/$(detect_net_prefix)/g" "$path" | kubectl --context "$context" apply -f -
}
