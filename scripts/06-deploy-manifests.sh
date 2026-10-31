#!/usr/bin/env bash
# manifests/<cluster>/*.yaml dosyalarını sırayla uygular
source "$(dirname "$0")/lib.sh"

for c in $CLUSTERS; do
  log "Manifestler -> $c"
  for f in "$ROOT_DIR/manifests/$c"/*.yaml; do
    echo "  - $(basename "$f")"
    apply_rendered "$(ctx "$c")" "$f"
  done
done

log "Pod'lar bekleniyor"
kubectl --context "$(ctx dmz)" -n edge-lb rollout status deploy/edge-lb --timeout=120s
kubectl --context "$(ctx cluster-a)" -n api-a rollout status deploy/api-a --timeout=120s
kubectl --context "$(ctx cluster-b)" -n api-b rollout status deploy/api-b --timeout=120s
