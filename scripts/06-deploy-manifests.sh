#!/usr/bin/env bash
# manifests/<cluster>/*.yaml dosyalarını sırayla uygular.
# cluster-b aktifse manifests/<cluster>/cluster-b/*.yaml da dahil edilir; dosyalar
# numaralarına göre birlikte sıralanır (ör. 05-api-a-backend.yaml, 10-api-a.yaml'dan önce).
source "$(dirname "$0")/lib.sh"

for c in $CLUSTERS; do
  log "Manifestler -> $c"
  dirs=("$ROOT_DIR/manifests/$c")
  if has_cluster cluster-b && [[ -d "$ROOT_DIR/manifests/$c/cluster-b" ]]; then
    dirs+=("$ROOT_DIR/manifests/$c/cluster-b")
  fi
  files=$(for d in "${dirs[@]}"; do for f in "$d"/*.yaml; do echo "$(basename "$f")|$f"; done; done | sort | cut -d'|' -f2)
  for f in $files; do
    echo "  - ${f#"$ROOT_DIR"/manifests/}"
    apply_rendered "$(ctx "$c")" "$f"
  done
done

log "Pod'lar bekleniyor"
kubectl --context "$(ctx dmz)" -n edge-lb rollout status deploy/edge-lb --timeout=120s
kubectl --context "$(ctx cluster-a)" -n api-a rollout status deploy/api-a --timeout=120s
if has_cluster cluster-b; then
  kubectl --context "$(ctx cluster-b)" -n api-b rollout status deploy/api-b --timeout=120s
fi
