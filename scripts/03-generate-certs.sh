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

# Edge -> DMZ zone geçişi: WAF ile DMZ ingress gateway arası karşılıklı TLS (mTLS).
# Ayrı bir CA: DMZ ingress yalnızca bu CA'nın imzaladığı istemci sertifikasını (edge-waf) kabul eder.
mkdir -p edge-dmz
if [[ ! -f edge-dmz/waf-client.crt ]]; then
  log "Edge -> DMZ mTLS sertifikaları üretiliyor"
  openssl req -x509 -new -nodes -newkey rsa:2048 -sha256 -days 3650 \
    -keyout edge-dmz/ca-key.pem -out edge-dmz/ca.pem \
    -subj "/O=${MESH_ID}/CN=Edge-DMZ Zone CA" \
    -addext "basicConstraints=critical,CA:true" \
    -addext "keyUsage=critical,keyCertSign,cRLSign"
  # Sunucu: DMZ ingress gateway
  openssl req -new -nodes -newkey rsa:2048 -sha256 \
    -keyout edge-dmz/dmz-server.key -out edge-dmz/dmz-server.csr -subj "/CN=*.${APPS_DOMAIN}"
  printf 'basicConstraints=CA:false\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\nsubjectAltName=DNS:*.%s\n' \
    "$APPS_DOMAIN" > edge-dmz/server-ext.cnf
  openssl x509 -req -sha256 -days 397 -in edge-dmz/dmz-server.csr \
    -CA edge-dmz/ca.pem -CAkey edge-dmz/ca-key.pem -CAcreateserial \
    -extfile edge-dmz/server-ext.cnf -out edge-dmz/dmz-server.crt
  # İstemci: edge-waf
  openssl req -new -nodes -newkey rsa:2048 -sha256 \
    -keyout edge-dmz/waf-client.key -out edge-dmz/waf-client.csr -subj "/O=${MESH_ID}/CN=edge-waf"
  printf 'basicConstraints=CA:false\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=clientAuth\n' \
    > edge-dmz/client-ext.cnf
  openssl x509 -req -sha256 -days 397 -in edge-dmz/waf-client.csr \
    -CA edge-dmz/ca.pem -CAkey edge-dmz/ca-key.pem -CAcreateserial \
    -extfile edge-dmz/client-ext.cnf -out edge-dmz/waf-client.crt
fi

# Partner kanalı: partner'lar edge'e kendi istemci sertifikalarıyla bağlanır. Ayrı bir "Partner CA";
# gerçekte her partner'ın sertifikası kurumun partner PKI'ından (onboarding sırasında) verilir.
#   acme   : izin listesinde (geçerli partner)
#   globex : aynı CA'dan ama izin listesinde değil (gateway AuthZ'de 403)
#   initech: izin listesinde, düşük global kotalı partner (07 · data, global rate limit testi)
#   rogue  : başka bir CA'dan, CN=acme (edge'de TLS el sıkışması reddedilir)
mkdir -p partner
if [[ ! -f partner/initech.crt ]]; then
  log "Partner CA ve partner istemci sertifikaları üretiliyor"
  openssl req -x509 -new -nodes -newkey rsa:2048 -sha256 -days 3650 \
    -keyout partner/ca-key.pem -out partner/ca.pem \
    -subj "/O=${MESH_ID}/CN=Partner CA" \
    -addext "basicConstraints=critical,CA:true" \
    -addext "keyUsage=critical,keyCertSign,cRLSign"
  printf 'basicConstraints=CA:false\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=clientAuth\n' \
    > partner/client-ext.cnf
  for p in acme globex initech; do
    openssl req -new -nodes -newkey rsa:2048 -sha256 \
      -keyout "partner/$p.key" -out "partner/$p.csr" -subj "/O=$p/CN=$p"
    openssl x509 -req -sha256 -days 397 -in "partner/$p.csr" \
      -CA partner/ca.pem -CAkey partner/ca-key.pem -CAcreateserial \
      -extfile partner/client-ext.cnf -out "partner/$p.crt"
  done
  openssl req -x509 -new -nodes -newkey rsa:2048 -sha256 -days 397 \
    -keyout partner/rogue.key -out partner/rogue.crt -subj "/O=acme/CN=acme" \
    -addext "extendedKeyUsage=clientAuth"
fi

# Şube kanalı: şube terminalleri cihaz sertifikasıyla bağlanır. "Branch CA" hem terminal sertifikalarını hem de
# branch-gateway'in sunucu sertifikasını (iç alan adı) verir. Gerçekte kurumsal iç PKI (ör. AD CS) ve cihaz yönetimi.
mkdir -p branch
if [[ ! -f "branch/${BRANCH_DEVICE}.crt" ]]; then
  log "Branch CA, branch-gateway sunucu sertifikası ve terminal sertifikası üretiliyor"
  openssl req -x509 -new -nodes -newkey rsa:2048 -sha256 -days 3650 \
    -keyout branch/ca-key.pem -out branch/ca.pem \
    -subj "/O=${MESH_ID}/CN=Branch CA" \
    -addext "basicConstraints=critical,CA:true" \
    -addext "keyUsage=critical,keyCertSign,cRLSign"
  openssl req -new -nodes -newkey rsa:2048 -sha256 \
    -keyout branch/gateway.key -out branch/gateway.csr -subj "/CN=${BRANCH_HOST}"
  printf 'basicConstraints=CA:false\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\nsubjectAltName=DNS:%s\n' \
    "$BRANCH_HOST" > branch/server-ext.cnf
  openssl x509 -req -sha256 -days 397 -in branch/gateway.csr \
    -CA branch/ca.pem -CAkey branch/ca-key.pem -CAcreateserial \
    -extfile branch/server-ext.cnf -out branch/gateway.crt
  openssl req -new -nodes -newkey rsa:2048 -sha256 \
    -keyout "branch/${BRANCH_DEVICE}.key" -out "branch/${BRANCH_DEVICE}.csr" -subj "/O=branch/OU=sube-0001/CN=${BRANCH_DEVICE}"
  printf 'basicConstraints=CA:false\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=clientAuth\n' \
    > branch/client-ext.cnf
  openssl x509 -req -sha256 -days 397 -in "branch/${BRANCH_DEVICE}.csr" \
    -CA branch/ca.pem -CAkey branch/ca-key.pem -CAcreateserial \
    -extfile branch/client-ext.cnf -out "branch/${BRANCH_DEVICE}.crt"
fi

# Realm imza anahtarları (09a · idp-token-exchange): iç JWT'yi Keycloak imzalar (RFC 8693 token exchange).
# Anahtar burada üretilip realm'e verilir (05b, realm JSON'undaki rsa key provider'ı); internal cluster'lar açık anahtarı
# RequestAuthentication'da inline JWKS olarak bilir: kurulum sırasına ve internal'dan IdP'ye ağ çağrısına bağımlılık yok.
# kid yazılmaz: Envoy, kid'siz JWK'yı her token için dener (Keycloak kid'i anahtardan kendisi türetir). Gerçekte HSM.
mkdir -p idp
for realm in customers partners staff; do
  [[ -f idp/$realm.jwks.json ]] && continue
  log "Realm imza anahtarı (RS256): $realm"
  openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out "idp/$realm.key" 2>/dev/null   # PKCS#8 (Keycloak bunu ister)
  openssl req -new -x509 -sha256 -days 397 -key "idp/$realm.key" -subj "/CN=$realm" -out "idp/$realm.crt"
  # JWK: n = modülün base64url'i, e = 65537 (AQAB)
  n=$(openssl rsa -in "idp/$realm.key" -noout -modulus | cut -d= -f2 | xxd -r -p | base64 -w0 | tr '+/' '-_' | tr -d '=')
  printf '{"keys":[{"kty":"RSA","use":"sig","alg":"RS256","n":"%s","e":"AQAB"}]}' "$n" > "idp/$realm.jwks.json"
done

# Uygulama bütünlük kanıtı (attestation) sağlayıcısının anahtarı (09c · mobile-binding). Gerçekte Google Play Integrity /
# Apple App Attest imzalar ve banka yalnızca açık anahtarı bilir; lab'de mobile-sim bu sağlayıcıyı da taklit eder.
mkdir -p attest
if [[ ! -f attest/attest.pub ]]; then
  log "Attestation sağlayıcı anahtarı (ES256)"
  openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-256 -out attest/attest.key 2>/dev/null
  openssl pkey -in attest/attest.key -pubout -out attest/attest.pub
fi

# Image imzalama anahtarı (cosign). Gerçekte özel anahtar KMS/HSM'de (ör. Vault Transit) durur ve yalnızca CI kullanır.
mkdir -p cosign
if [[ ! -f cosign/cosign.pub ]]; then
  log "cosign anahtar çifti üretiliyor"
  docker run --rm -v "$CERT_DIR/cosign:/keys" -w /keys -e COSIGN_PASSWORD= "$COSIGN_IMAGE" generate-key-pair
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
