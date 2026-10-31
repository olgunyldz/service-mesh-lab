#!/usr/bin/env bash
# Ortak root CA + her cluster için intermediate CA üretir ve istio-system/cacerts secret'ı olarak yükler.
# Böylece cluster'lar arası gateway mTLS (ISTIO_MUTUAL) aynı güven zincirine dayanır.
source "$(dirname "$0")/lib.sh"

CERT_DIR="$ROOT_DIR/certs"
mkdir -p "$CERT_DIR"
cd "$CERT_DIR"

if [[ ! -f root-cert.pem ]]; then
  log "Root CA üretiliyor"
  openssl req -x509 -new -nodes -newkey rsa:4096 -sha256 -days 3650 \
    -keyout root-key.pem -out root-cert.pem \
    -subj "/O=${MESH_ID}/CN=Root CA" \
    -addext "basicConstraints=critical,CA:true" \
    -addext "keyUsage=critical,keyCertSign,cRLSign"
fi

# Edge (dış DMZ) TLS sertifikası. Mesh CA'sından bilerek AYRI bir CA ile imzalanır:
# gerçekte bu sertifika genel bir CA'dan (public CA) gelir ve kurumsal mesh CA'sıyla ilgisi yoktur.
mkdir -p edge
if [[ ! -f edge/edge.pem ]]; then
  log "Edge CA ve *.${APPS_DOMAIN} sertifikası üretiliyor"
  openssl req -x509 -new -nodes -newkey rsa:2048 -sha256 -days 3650 \
    -keyout edge/ca-key.pem -out edge/ca.pem \
    -subj "/O=Lab Public CA/CN=Lab Public Root CA" \
    -addext "basicConstraints=critical,CA:true" \
    -addext "keyUsage=critical,keyCertSign,cRLSign"
  openssl req -new -nodes -newkey rsa:2048 -sha256 \
    -keyout edge/tls.key -out edge/tls.csr -subj "/CN=*.${APPS_DOMAIN}"
  cat > edge/ext.cnf <<EOF
basicConstraints=CA:false
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=DNS:*.${APPS_DOMAIN},DNS:${APPS_DOMAIN},DNS:localhost
EOF
  openssl x509 -req -sha256 -days 397 -in edge/tls.csr \
    -CA edge/ca.pem -CAkey edge/ca-key.pem -CAcreateserial \
    -extfile edge/ext.cnf -out edge/tls.crt
  # HAProxy sertifika ve anahtarı tek dosyada ister
  cat edge/tls.crt edge/tls.key > edge/edge.pem
fi

for c in $CLUSTERS; do
  mkdir -p "$c"
  if [[ ! -f "$c/ca-cert.pem" ]]; then
    log "Intermediate CA üretiliyor: $c"
    cat > "$c/ext.cnf" <<EOF
basicConstraints=critical,CA:true,pathlen:0
keyUsage=critical,digitalSignature,keyEncipherment,keyCertSign,cRLSign
subjectAltName=URI:spiffe://${TRUST_DOMAIN}/ns/istio-system/sa/istiod
EOF
    openssl req -new -nodes -newkey rsa:4096 -sha256 \
      -keyout "$c/ca-key.pem" -out "$c/ca.csr" \
      -subj "/O=${MESH_ID}/CN=Intermediate CA ${c}"
    openssl x509 -req -sha256 -days 730 -in "$c/ca.csr" \
      -CA root-cert.pem -CAkey root-key.pem -CAcreateserial \
      -extfile "$c/ext.cnf" -out "$c/ca-cert.pem"
    cat "$c/ca-cert.pem" root-cert.pem > "$c/cert-chain.pem"
    cp root-cert.pem "$c/root-cert.pem"
  fi

  context=$(ctx "$c")
  kubectl --context "$context" create namespace istio-system --dry-run=client -o yaml | kubectl --context "$context" apply -f -
  kubectl --context "$context" -n istio-system create secret generic cacerts \
    --from-file="$c/ca-cert.pem" --from-file="$c/ca-key.pem" \
    --from-file="$c/root-cert.pem" --from-file="$c/cert-chain.pem" \
    --dry-run=client -o yaml | kubectl --context "$context" apply -f -
done
