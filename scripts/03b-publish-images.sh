#!/usr/bin/env bash
# Uygulama image'larını lab registry'ye (kurumsal iç registry'nin karşılığı) kopyalar ve cosign ile imzalar.
# Gerçekte bu adımı CI yapar: build -> tarama -> imza -> iç registry. Kyverno yalnızca imzalı image'ları kabul eder.
source "$(dirname "$0")/lib.sh"

KEYS="$ROOT_DIR/certs/cosign"
[[ -f "$KEYS/cosign.key" ]] || { echo "cosign anahtarı yok, önce 03-generate-certs.sh"; exit 1; }

# cosign kind ağında çalışır: kaynağı registry önbelleğinden çeker, lab registry'ye düz HTTP ile yazar
cosign() {
  docker run --rm --network kind -v "$KEYS:/keys:ro" -e COSIGN_PASSWORD= "$COSIGN_IMAGE" "$@"
}

# docker.io/curlimages/curl:8.11.1 -> cache-docker-io:5000/curlimages/curl:8.11.1
from_cache() { local reg=${1%%/*}; echo "$(cache_name "$reg"):5000/${1#*/}"; }

# --force: lab registry kalıcı, her kurulumda üzerine yazılır. Upstream'in imzası (.sig) da kopyalanır ve
# öncekini ezer; bu yüzden imza her seferinde yeniden atılır, imzalar birikmez.
copy() {
  cosign copy --allow-http-registry --force "$(from_cache "$1")" "$LAB_REGISTRY/$2" >/dev/null
}

verify() {
  cosign verify --key /keys/cosign.pub --allow-http-registry --allow-insecure-registry --insecure-ignore-tlog=true \
    "$LAB_REGISTRY/$1" >/dev/null 2>&1
}

for entry in $LAB_IMAGES; do
  src=${entry%%=*} dst=${entry#*=}
  log "Kopyala + imzala: $src -> $LAB_REGISTRY/$dst"
  copy "$src" "$dst"
  # Rekor (şeffaflık logu) internette; iç ortamda imza yalnızca registry'de tutulur
  cosign sign --key /keys/cosign.key --allow-http-registry --tlog-upload=false --yes "$LAB_REGISTRY/$dst" 2>&1 \
    | grep -v "^WARNING" || true
done

# Kendi servislerimiz (services/<ad>) ve kendi build'imiz olan üçüncü taraf image'lar (images/<ad>, ör. optimize
# Keycloak): host'ta build -> lab registry (127.0.0.1:<port>) -> imza. Gerçekte CI yapar (15 · ci).
for entry in $LAB_BUILDS; do
  svc=${entry%%:*} ver=${entry#*:}
  dir="$ROOT_DIR/services/$svc"
  [[ -d "$dir" ]] || dir="$ROOT_DIR/images/$svc"
  log "Build + imzala: ${dir#"$ROOT_DIR"/} -> $LAB_REGISTRY/lab/$svc:$ver"
  docker build -q -t "localhost:$LAB_REGISTRY_HOST_PORT/lab/$svc:$ver" \
    --build-arg GO_BUILD_IMAGE="$GO_BUILD_IMAGE" --build-arg GO_RUNTIME_IMAGE="$GO_RUNTIME_IMAGE" \
    --build-arg KEYCLOAK_BASE_IMAGE="$KEYCLOAK_BASE_IMAGE" \
    --build-arg VERSION="$ver" "$dir" >/dev/null
  docker push -q "localhost:$LAB_REGISTRY_HOST_PORT/lab/$svc:$ver" >/dev/null
  verify "lab/$svc:$ver" && { echo "  zaten imzalı (aynı digest)"; continue; }
  cosign sign --key /keys/cosign.key --allow-http-registry --tlog-upload=false --yes "$LAB_REGISTRY/lab/$svc:$ver" 2>&1 \
    | grep -v "^WARNING" || true
done

# Negatif test: aynı içerik, imzasız
src=$(echo "$LAB_IMAGES" | tr ' ' '\n' | grep curl | cut -d= -f1)
log "İmzasız kopya (negatif test): $LAB_REGISTRY/$LAB_UNSIGNED_IMAGE"
copy "$src" "$LAB_UNSIGNED_IMAGE"

log "Doğrulama"
for dst in $(for e in $LAB_IMAGES; do echo "${e#*=}"; done) $(for e in $LAB_BUILDS; do echo "lab/${e%%:*}:${e#*:}"; done); do
  if verify "$dst"; then echo "  ✔ imzalı: $dst"; else echo "  ✘ imza doğrulanamadı: $dst"; exit 1; fi
done
# cosign copy upstream'in keyless imzasını da taşır; bizim anahtarımızla doğrulanmamalı
if verify "$LAB_UNSIGNED_IMAGE"; then echo "  ✘ beklenmedik imza: $LAB_UNSIGNED_IMAGE"; exit 1; fi
echo "  ✔ bizim anahtarla imzasız: $LAB_UNSIGNED_IMAGE"
