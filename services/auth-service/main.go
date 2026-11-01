// auth-service: DMZ kanal gateway'lerinin harici yetkilendirme (Envoy ext_authz, HTTP) servisi.
//
// Her istekte gateway buraya sorar. auth-service:
//  1. Authorization: Bearer <access token>'ı doğrular (Keycloak JWKS: imza RS256, iss, exp, azp, rol),
//  2. kanal kurallarını uygular (kanal, gateway'in eklediği x-auth-channel header'ından gelir; istemci değiştiremez),
//  3. içeri girecek kısa ömürlü iç JWT'yi kendi anahtarıyla imzalar ve x-user-jwt olarak döner.
//
// Dış token DMZ'de kalır (gateway Authorization'ı siler); internal servisler yalnızca iç JWT'yi görür.
// Yalnızca standart kütüphane kullanır.
package main

import (
	"crypto"
	"crypto/rand"
	"crypto/rsa"
	"crypto/sha256"
	"crypto/x509"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"encoding/pem"
	"errors"
	"fmt"
	"log"
	"math/big"
	"net/http"
	"os"
	"slices"
	"strings"
	"sync"
	"time"
)

var version = "dev" // build sırasında -ldflags ile verilir

// Kanal kuralları: hangi realm'in, hangi client'ın (azp) token'ı, hangi rollerle kabul edilir
type channelRule struct {
	realm   string
	clients []string // boşsa: partner kanalı, azp == sertifika CN'i (x-partner-id)
	roles   []string // en az biri gerekli; iç JWT'ye yalnızca bunlar taşınır
}

var rules = map[string]channelRule{
	"web":     {realm: "customers", clients: []string{"web-bff"}, roles: []string{"customer"}},
	"mobile":  {realm: "customers", clients: []string{"mobile-app"}, roles: []string{"customer"}},
	"partner": {realm: "partners", roles: []string{"partner"}},
	"branch":  {realm: "staff", clients: []string{"branch-teller"}, roles: []string{"teller", "operations"}},
}

type config struct {
	issuerBase  string // dış token'ların issuer öneki: https://sso.../realms/
	jwksBase    string // JWKS'in mesh içi adresi: http://keycloak.auth.svc.cluster.local/realms/
	internalIss string
	internalAud string
	ttl         time.Duration
	kid         string
	key         *rsa.PrivateKey
}

func main() {
	key, err := loadKey(env("SIGNING_KEY", "/keys/signing.key"))
	if err != nil {
		log.Fatalf("imza anahtarı: %v", err)
	}
	cfg := &config{
		issuerBase:  env("ISSUER_BASE", "https://sso.apps.example.local:8443/realms/"),
		jwksBase:    env("JWKS_BASE", "http://keycloak.auth.svc.cluster.local/realms/"),
		internalIss: env("INTERNAL_ISSUER", "auth.dmz.corp.mesh"),
		internalAud: env("INTERNAL_AUDIENCE", "internal-apis"),
		ttl:         5 * time.Minute,
		kid:         env("SIGNING_KID", "internal-1"),
		key:         key,
	}
	a := &authz{cfg: cfg, jwks: newJWKSCache(cfg.jwksBase), cache: map[string]cached{}}
	go a.evictLoop()

	srv := &http.Server{
		Addr:              ":" + env("PORT", "8080"),
		Handler:           a,
		ReadHeaderTimeout: 2 * time.Second,
		ReadTimeout:       5 * time.Second,
		WriteTimeout:      5 * time.Second,
		MaxHeaderBytes:    64 << 10,
	}
	log.Printf("auth-service %s dinliyor: %s (iç issuer %s, kid %s)", version, srv.Addr, cfg.internalIss, cfg.kid)
	log.Fatal(srv.ListenAndServe())
}

type cached struct {
	jwt string
	exp time.Time
}

type authz struct {
	cfg   *config
	jwks  *jwksCache
	mu    sync.Mutex
	cache map[string]cached // dış token (+ kanal bağlamı) -> iç JWT
}

type denial struct {
	status int
	code   string
	reason string // yalnızca loga
}

func (d *denial) Error() string { return d.code + ": " + d.reason }

func deny(status int, code, reason string) *denial { return &denial{status, code, reason} }

// ServeHTTP: ext_authz kontrol isteği. Yol ve metot asıl isteğinkidir; gövde gelmez.
func (a *authz) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	channel := r.Header.Get("x-auth-channel")
	if channel == "" { // gateway'den gelmeyen istek: yalnızca kendi sağlık kontrolü
		if r.URL.Path == "/healthz" {
			w.WriteHeader(http.StatusOK)
			return
		}
		http.Error(w, "not found", http.StatusNotFound)
		return
	}
	jwt, sub, err := a.authorize(r, channel)
	if err != nil {
		var d *denial
		if !errors.As(err, &d) {
			d = deny(http.StatusServiceUnavailable, "auth_unavailable", err.Error())
		}
		log.Printf("RED channel=%s path=%s status=%d sebep=%q request_id=%q", channel, r.URL.Path, d.status, d.reason, r.Header.Get("x-request-id"))
		if d.status == http.StatusUnauthorized {
			w.Header().Set("WWW-Authenticate", `Bearer error="invalid_token"`)
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(d.status)
		json.NewEncoder(w).Encode(map[string]string{"error": d.code})
		return
	}
	log.Printf("İZİN channel=%s path=%s sub=%s request_id=%q", channel, r.URL.Path, sub, r.Header.Get("x-request-id"))
	w.Header().Set("x-user-jwt", jwt)
	w.WriteHeader(http.StatusOK)
}

func (a *authz) authorize(r *http.Request, channel string) (string, string, error) {
	rule, ok := rules[channel]
	if !ok {
		return "", "", deny(http.StatusForbidden, "unknown_channel", channel)
	}
	token, ok := strings.CutPrefix(r.Header.Get("Authorization"), "Bearer ")
	if !ok || token == "" {
		return "", "", deny(http.StatusUnauthorized, "missing_token", "Authorization: Bearer yok")
	}
	partnerID := r.Header.Get("x-partner-id")                    // edge, sertifika CN'inden yazar
	device := subjectCN(r.Header.Get("x-forwarded-client-cert")) // branch-gateway, cihaz sertifikasından

	ck := cacheKey(token, channel, partnerID, device)
	a.mu.Lock()
	c, hit := a.cache[ck]
	a.mu.Unlock()
	if hit && time.Until(c.exp) > 30*time.Second {
		return c.jwt, "(önbellek)", nil
	}

	claims, err := a.verifyExternal(token, rule.realm)
	if err != nil {
		return "", "", err
	}
	azp, _ := claims["azp"].(string)
	switch {
	case channel == "partner":
		if partnerID == "" || azp != partnerID {
			return "", "", deny(http.StatusForbidden, "token_not_bound_to_certificate",
				fmt.Sprintf("azp=%q sertifika=%q", azp, partnerID))
		}
	case !slices.Contains(rule.clients, azp):
		return "", "", deny(http.StatusForbidden, "wrong_client_for_channel", "azp="+azp)
	}
	if channel == "branch" && device == "" {
		return "", "", deny(http.StatusForbidden, "device_certificate_required", "XFCC yok")
	}
	roles := intersect(realmRoles(claims), rule.roles)
	if len(roles) == 0 {
		return "", "", deny(http.StatusForbidden, "insufficient_role", fmt.Sprint(realmRoles(claims)))
	}

	sub, _ := claims["sub"].(string)
	now := time.Now()
	exp := now.Add(a.cfg.ttl)
	if te := numericTime(claims["exp"]); te.Before(exp) {
		exp = te // iç JWT, dış token'dan uzun yaşamaz
	}
	internal := map[string]any{
		"iss":     a.cfg.internalIss,
		"aud":     a.cfg.internalAud,
		"sub":     sub,
		"roles":   roles,
		"channel": channel,
		"idp":     rule.realm,
		"azp":     azp,
		"iat":     now.Unix(),
		"exp":     exp.Unix(),
		"jti":     randomHex(16),
	}
	if u, ok := claims["preferred_username"].(string); ok && channel != "partner" {
		internal["preferred_username"] = u
	}
	if channel == "partner" {
		internal["partner_id"] = partnerID
	}
	if channel == "branch" {
		internal["branch_device"] = device
	}
	jwt, err := sign(a.cfg.key, a.cfg.kid, internal)
	if err != nil {
		return "", "", err
	}
	a.mu.Lock()
	if len(a.cache) < 10000 {
		a.cache[ck] = cached{jwt, exp}
	}
	a.mu.Unlock()
	return jwt, sub, nil
}

// verifyExternal: Keycloak access token'ı (RS256) doğrular
func (a *authz) verifyExternal(token, realm string) (map[string]any, error) {
	parts := strings.Split(token, ".")
	if len(parts) != 3 {
		return nil, deny(http.StatusUnauthorized, "invalid_token", "JWT biçimi değil")
	}
	var hdr struct{ Alg, Kid string }
	if err := decodeSegment(parts[0], &hdr); err != nil || hdr.Alg != "RS256" {
		return nil, deny(http.StatusUnauthorized, "invalid_token", "başlık/alg: "+hdr.Alg)
	}
	var claims map[string]any
	if err := decodeSegment(parts[1], &claims); err != nil {
		return nil, deny(http.StatusUnauthorized, "invalid_token", "payload")
	}
	// iss imzadan önce kontrol edilir: başka realm'in token'ı için JWKS hiç çekilmez
	if iss, _ := claims["iss"].(string); iss != a.cfg.issuerBase+realm {
		return nil, deny(http.StatusForbidden, "wrong_realm_for_channel", "iss="+iss)
	}
	pub, err := a.jwks.key(realm, hdr.Kid)
	if err != nil {
		return nil, err
	}
	sig, err := base64.RawURLEncoding.DecodeString(parts[2])
	if err != nil {
		return nil, deny(http.StatusUnauthorized, "invalid_token", "imza kodlaması")
	}
	digest := sha256.Sum256([]byte(parts[0] + "." + parts[1]))
	if rsa.VerifyPKCS1v15(pub, crypto.SHA256, digest[:], sig) != nil {
		return nil, deny(http.StatusUnauthorized, "invalid_token", "imza geçersiz")
	}
	now := time.Now()
	if numericTime(claims["exp"]).Before(now.Add(-30 * time.Second)) {
		return nil, deny(http.StatusUnauthorized, "invalid_token", "süresi dolmuş")
	}
	if nbf, ok := claims["nbf"]; ok && numericTime(nbf).After(now.Add(30*time.Second)) {
		return nil, deny(http.StatusUnauthorized, "invalid_token", "henüz geçerli değil")
	}
	if typ, _ := claims["typ"].(string); typ != "Bearer" {
		return nil, deny(http.StatusUnauthorized, "invalid_token", "access token değil: "+typ)
	}
	return claims, nil
}

func (a *authz) evictLoop() {
	for range time.Tick(time.Minute) {
		a.mu.Lock()
		for k, c := range a.cache {
			if time.Now().After(c.exp) {
				delete(a.cache, k)
			}
		}
		a.mu.Unlock()
	}
}

// --- Keycloak JWKS önbelleği (realm başına) ---

type jwksCache struct {
	base   string
	client *http.Client
	mu     sync.Mutex
	keys   map[string]map[string]*rsa.PublicKey // realm -> kid -> anahtar
	last   map[string]time.Time
}

func newJWKSCache(base string) *jwksCache {
	return &jwksCache{base: base, client: &http.Client{Timeout: 3 * time.Second},
		keys: map[string]map[string]*rsa.PublicKey{}, last: map[string]time.Time{}}
}

// key: bilinmeyen kid'de (anahtar rotasyonu) en fazla 10 sn'de bir yeniden çeker
func (c *jwksCache) key(realm, kid string) (*rsa.PublicKey, error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if k, ok := c.keys[realm][kid]; ok && time.Since(c.last[realm]) < 10*time.Minute {
		return k, nil
	}
	if time.Since(c.last[realm]) > 10*time.Second || c.keys[realm] == nil {
		keys, err := c.fetch(realm)
		if err != nil {
			if k, ok := c.keys[realm][kid]; ok { // IdP geçici erişilemezse eldeki anahtar kullanılır
				return k, nil
			}
			return nil, fmt.Errorf("JWKS alınamadı (%s): %w", realm, err)
		}
		c.keys[realm], c.last[realm] = keys, time.Now()
	}
	if k, ok := c.keys[realm][kid]; ok {
		return k, nil
	}
	return nil, deny(http.StatusUnauthorized, "invalid_token", "bilinmeyen kid: "+kid)
}

func (c *jwksCache) fetch(realm string) (map[string]*rsa.PublicKey, error) {
	resp, err := c.client.Get(c.base + realm + "/protocol/openid-connect/certs")
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, errors.New(resp.Status)
	}
	var set struct {
		Keys []struct{ Kid, Kty, Use, Alg, N, E string }
	}
	if err := json.NewDecoder(resp.Body).Decode(&set); err != nil {
		return nil, err
	}
	out := map[string]*rsa.PublicKey{}
	for _, k := range set.Keys {
		if k.Kty != "RSA" || (k.Use != "" && k.Use != "sig") {
			continue
		}
		n, err1 := base64.RawURLEncoding.DecodeString(k.N)
		e, err2 := base64.RawURLEncoding.DecodeString(k.E)
		if err1 != nil || err2 != nil {
			continue
		}
		out[k.Kid] = &rsa.PublicKey{N: new(big.Int).SetBytes(n), E: int(new(big.Int).SetBytes(e).Int64())}
	}
	return out, nil
}

// --- yardımcılar ---

func sign(key *rsa.PrivateKey, kid string, claims map[string]any) (string, error) {
	h, _ := json.Marshal(map[string]string{"alg": "RS256", "typ": "JWT", "kid": kid})
	p, err := json.Marshal(claims)
	if err != nil {
		return "", err
	}
	unsigned := base64.RawURLEncoding.EncodeToString(h) + "." + base64.RawURLEncoding.EncodeToString(p)
	digest := sha256.Sum256([]byte(unsigned))
	sig, err := rsa.SignPKCS1v15(rand.Reader, key, crypto.SHA256, digest[:])
	if err != nil {
		return "", err
	}
	return unsigned + "." + base64.RawURLEncoding.EncodeToString(sig), nil
}

func decodeSegment(s string, v any) error {
	b, err := base64.RawURLEncoding.DecodeString(s)
	if err != nil {
		return err
	}
	return json.Unmarshal(b, v)
}

func realmRoles(claims map[string]any) []string {
	ra, _ := claims["realm_access"].(map[string]any)
	list, _ := ra["roles"].([]any)
	var out []string
	for _, r := range list {
		if s, ok := r.(string); ok {
			out = append(out, s)
		}
	}
	return out
}

func intersect(have, allowed []string) []string {
	var out []string
	for _, r := range have {
		if slices.Contains(allowed, r) {
			out = append(out, r)
		}
	}
	return out
}

func numericTime(v any) time.Time {
	f, _ := v.(float64)
	return time.Unix(int64(f), 0)
}

// subjectCN: x-forwarded-client-cert içindeki Subject="CN=...,..." alanından CN
func subjectCN(xfcc string) string {
	for _, part := range strings.Split(xfcc, ";") {
		if v, ok := strings.CutPrefix(part, "Subject="); ok {
			for _, rdn := range strings.Split(strings.Trim(v, `"`), ",") {
				if cn, ok := strings.CutPrefix(strings.TrimSpace(rdn), "CN="); ok {
					return cn
				}
			}
		}
	}
	return ""
}

func cacheKey(parts ...string) string {
	h := sha256.Sum256([]byte(strings.Join(parts, "\x00")))
	return hex.EncodeToString(h[:])
}

func randomHex(n int) string {
	b := make([]byte, n)
	rand.Read(b)
	return hex.EncodeToString(b)
}

func loadKey(path string) (*rsa.PrivateKey, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	blk, _ := pem.Decode(b)
	if blk == nil {
		return nil, errors.New("PEM değil")
	}
	if k, err := x509.ParsePKCS1PrivateKey(blk.Bytes); err == nil {
		return k, nil
	}
	k, err := x509.ParsePKCS8PrivateKey(blk.Bytes)
	if err != nil {
		return nil, err
	}
	rk, ok := k.(*rsa.PrivateKey)
	if !ok {
		return nil, errors.New("RSA anahtarı değil")
	}
	return rk, nil
}

func env(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}
