#!/usr/bin/env bash
source "$(dirname "$0")/lib.sh"

log "Gerekli araçlar kontrol ediliyor"
missing=0
for tool in docker kind kubectl helm istioctl openssl; do
  if command -v "$tool" >/dev/null 2>&1; then
    printf '  [ok]   %s\n' "$tool"
  else
    printf '  [YOK]  %s\n' "$tool"; missing=1
  fi
done

docker info >/dev/null 2>&1 || { echo "Docker çalışmıyor."; missing=1; }

if [[ $missing -eq 1 ]]; then
  echo
  echo "Eksik araçları kurun (Windows): winget install Kubernetes.kind Helm.Helm"
  echo "istioctl: https://github.com/istio/istio/releases/tag/${ISTIO_VERSION}"
  exit 1
fi
