#!/usr/bin/env bash
source "$(dirname "$0")/lib.sh"

for c in $CLUSTERS; do
  log "Siliniyor: $c"
  kind delete cluster --name "$c" || true
  # Docker Desktop bazen container'ı zamanında durduramıyor ("did not receive an exit event");
  # kind silemezse kalan node container'larını doğrudan kaldır
  leftovers=$(docker ps -aq --filter "label=io.x-k8s.kind.cluster=$c")
  if [[ -n "$leftovers" ]]; then
    echo "  kalan container'lar siliniyor"
    docker rm -f -v $leftovers >/dev/null
  fi
done

for arg in "$@"; do
  case "$arg" in
    --certs)
      rm -rf "$ROOT_DIR/certs" ;;
    --cache)
      # Registry önbelleği normalde korunur (sonraki kurulumlar hızlı olsun diye)
      for entry in $REGISTRY_MIRRORS; do
        name=$(cache_name "${entry%%=*}")
        log "Önbellek siliniyor: $name"
        docker rm -f "$name" >/dev/null 2>&1 || true
        docker volume rm "$name" >/dev/null 2>&1 || true
      done ;;
  esac
done
