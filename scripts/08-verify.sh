#!/usr/bin/env bash
# Uçtan uca trafik testleri
source "$(dirname "$0")/lib.sh"

H="apps.example.local"

log "1) İnternet -> edge-lb -> DMZ gw -> cluster-a gw -> waypoint -> api-a"
curl -s -H "Host: api-a.$H" http://localhost:8080/ | head -20

log "2) İnternet -> edge-lb -> DMZ gw -> cluster-b gw -> waypoint -> api-b"
curl -s -H "Host: api-b.$H" http://localhost:8080/ | head -20

log "3) api-a -> egress gw (cluster-a) -> cluster-b gw -> api-b"
curl -s -X POST -H "Host: api-a.$H" -d 'merhaba' http://localhost:8080/api/echo

log "4) api-a -> egress gw -> httpbin.org"
kubectl --context "$(ctx cluster-a)" -n api-a exec deploy/api-a -- \
  wget -qO- -T 10 http://httpbin.org/headers || echo "(egress başarısız)"

log "5) Mesh durumu (ztunnel workload listesi, cluster-a)"
istioctl --context "$(ctx cluster-a)" ztunnel-config workloads | grep -E "api-a|NAMESPACE" || true

log "6) Gözlemlenebilirlik (Kiali / Grafana)"
for c in $CLUSTERS; do
  k=$(http_code "http://localhost:$(kiali_port "$c")/kiali/api/status")
  g=$(http_code "http://localhost:$(grafana_port "$c")/api/health")
  printf '  %-10s Kiali http://localhost:%s/kiali -> %s   Grafana http://localhost:%s -> %s\n' \
    "$c" "$(kiali_port "$c")" "$k" "$(grafana_port "$c")" "$g"
done
