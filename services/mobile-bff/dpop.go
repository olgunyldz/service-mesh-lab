package main

// DPoP (RFC 9449) kanıtı ve uygulama bütünlük kanıtı (attestation) doğrulaması (09c · mobile-binding).
// Yalnızca ES256 (ECDSA P-256): mobil cihazların güvenli donanımı (Secure Enclave / StrongBox) bunu destekler.
// Aynı dosya auth-service'te de var (servisler bağımsız modüller).

import (
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"math/big"
	"strconv"
	"strings"
	"time"
)

type ecJWK struct {
	Kty string `json:"kty"`
	Crv string `json:"crv"`
	X   string `json:"x"`
	Y   string `json:"y"`
}

// thumbprint: RFC 7638 (yalnızca zorunlu alanlar, sözlük sırasıyla)
func (k ecJWK) thumbprint() string {
	b := []byte(`{"crv":"` + k.Crv + `","kty":"` + k.Kty + `","x":"` + k.X + `","y":"` + k.Y + `"}`)
	h := sha256.Sum256(b)
	return base64.RawURLEncoding.EncodeToString(h[:])
}

func (k ecJWK) publicKey() (*ecdsa.PublicKey, error) {
	if k.Kty != "EC" || k.Crv != "P-256" {
		return nil, errors.New("yalnızca EC P-256")
	}
	x, err1 := base64.RawURLEncoding.DecodeString(k.X)
	y, err2 := base64.RawURLEncoding.DecodeString(k.Y)
	if err1 != nil || err2 != nil || len(x) != 32 || len(y) != 32 {
		return nil, errors.New("JWK koordinatları geçersiz")
	}
	pub := &ecdsa.PublicKey{Curve: elliptic.P256(), X: new(big.Int).SetBytes(x), Y: new(big.Int).SetBytes(y)}
	if !pub.Curve.IsOnCurve(pub.X, pub.Y) {
		return nil, errors.New("nokta eğri üzerinde değil")
	}
	return pub, nil
}

type jws struct {
	header  map[string]json.RawMessage
	claims  map[string]any
	input   string // imzalanan kısım: header.payload
	sig     []byte
	headerT string // typ
	alg     string
}

func parseJWS(token string) (*jws, error) {
	parts := strings.Split(token, ".")
	if len(parts) != 3 {
		return nil, errors.New("JWS biçimi değil")
	}
	j := &jws{input: parts[0] + "." + parts[1]}
	hb, err := base64.RawURLEncoding.DecodeString(parts[0])
	if err != nil || json.Unmarshal(hb, &j.header) != nil {
		return nil, errors.New("başlık çözülemedi")
	}
	pb, err := base64.RawURLEncoding.DecodeString(parts[1])
	if err != nil || json.Unmarshal(pb, &j.claims) != nil {
		return nil, errors.New("gövde çözülemedi")
	}
	if j.sig, err = base64.RawURLEncoding.DecodeString(parts[2]); err != nil {
		return nil, errors.New("imza çözülemedi")
	}
	json.Unmarshal(j.header["typ"], &j.headerT)
	json.Unmarshal(j.header["alg"], &j.alg)
	return j, nil
}

// verifyES256: JWS ES256 imzası r||s (64 bayt)
func verifyES256(pub *ecdsa.PublicKey, input string, sig []byte) bool {
	if len(sig) != 64 {
		return false
	}
	h := sha256.Sum256([]byte(input))
	return ecdsa.Verify(pub, h[:], new(big.Int).SetBytes(sig[:32]), new(big.Int).SetBytes(sig[32:]))
}

type dpopProof struct {
	jkt string
	jwk ecJWK
	jti string
}

// verifyDPoP: kanıt cihaz anahtarıyla imzalı mı, bu istek (metot + URL) ve bu token (ath) için mi, taze mi.
// Tekrar (jti) kontrolü çağıranın işi (paylaşılan depo).
func verifyDPoP(proof, method, htu, accessToken string, skew time.Duration) (*dpopProof, error) {
	j, err := parseJWS(proof)
	if err != nil {
		return nil, err
	}
	if j.headerT != "dpop+jwt" || j.alg != "ES256" {
		return nil, fmt.Errorf("typ/alg: %s/%s", j.headerT, j.alg)
	}
	var k ecJWK
	if json.Unmarshal(j.header["jwk"], &k) != nil {
		return nil, errors.New("jwk yok")
	}
	pub, err := k.publicKey()
	if err != nil {
		return nil, err
	}
	if !verifyES256(pub, j.input, j.sig) {
		return nil, errors.New("imza geçersiz")
	}
	if m, _ := j.claims["htm"].(string); m != method {
		return nil, fmt.Errorf("htm %q, beklenen %q", m, method)
	}
	if u, _ := j.claims["htu"].(string); u != htu {
		return nil, fmt.Errorf("htu %q, beklenen %q", u, htu)
	}
	iat, _ := j.claims["iat"].(float64)
	if d := time.Since(time.Unix(int64(iat), 0)); d > skew || d < -skew {
		return nil, fmt.Errorf("iat eski/ileri: %s", d.Round(time.Second))
	}
	jti, _ := j.claims["jti"].(string)
	if len(jti) < 16 {
		return nil, errors.New("jti yok")
	}
	if accessToken != "" {
		h := sha256.Sum256([]byte(accessToken))
		if a, _ := j.claims["ath"].(string); a != base64.RawURLEncoding.EncodeToString(h[:]) {
			return nil, errors.New("ath token'la eşleşmiyor")
		}
	}
	return &dpopProof{jkt: k.thumbprint(), jwk: k, jti: jti}, nil
}

type attestation struct {
	appID, version string
}

// verifyAttestation: uygulama bütünlük kanıtı (lab'de Play Integrity / App Attest yerine imzalı test JWT'si).
// Kanıt cihaz anahtarına bağlı (jkt) olmalı: başka cihazın kanıtı kopyalanamaz.
func verifyAttestation(token string, pub *ecdsa.PublicKey, appID, minVersion, jkt string) (*attestation, error) {
	j, err := parseJWS(token)
	if err != nil {
		return nil, err
	}
	if j.alg != "ES256" || !verifyES256(pub, j.input, j.sig) {
		return nil, errors.New("attestation imzası geçersiz")
	}
	c := j.claims
	if iss, _ := c["iss"].(string); iss != "lab-attestation" {
		return nil, errors.New("iss")
	}
	if a, _ := c["app_id"].(string); a != appID {
		return nil, fmt.Errorf("app_id %q", a)
	}
	if v, _ := c["integrity"].(string); v != "MEETS_DEVICE_INTEGRITY" {
		return nil, fmt.Errorf("cihaz bütünlüğü: %q", v)
	}
	if k, _ := c["jkt"].(string); k != jkt {
		return nil, errors.New("kanıt bu cihaz anahtarına ait değil")
	}
	exp, _ := c["exp"].(float64)
	if time.Now().After(time.Unix(int64(exp), 0)) {
		return nil, errors.New("süresi dolmuş")
	}
	v, _ := c["app_version"].(string)
	return &attestation{appID: appID, version: v}, nil
}

// versionLess: "3.2.0" < "3.10.1" (sayısal karşılaştırma)
func versionLess(a, b string) bool {
	pa, pb := strings.Split(a, "."), strings.Split(b, ".")
	for i := 0; i < len(pa) || i < len(pb); i++ {
		var x, y int
		if i < len(pa) {
			x, _ = strconv.Atoi(pa[i])
		}
		if i < len(pb) {
			y, _ = strconv.Atoi(pb[i])
		}
		if x != y {
			return x < y
		}
	}
	return false
}
