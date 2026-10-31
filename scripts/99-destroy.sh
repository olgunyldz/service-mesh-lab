#!/usr/bin/env bash
source "$(dirname "$0")/lib.sh"

for c in $CLUSTERS; do
  log "Siliniyor: $c"
  kind delete cluster --name "$c" || true
done

if [[ "${1:-}" == "--certs" ]]; then
  rm -rf "$ROOT_DIR/certs"
fi
