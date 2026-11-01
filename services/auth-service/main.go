// auth-service: DMZ kanal gateway'lerinin harici yetkilendirme (Envoy ext_authz, HTTP) servisi; dokümandaki auth-proxy.
//
// Her istekte gateway (web'de web-token-handler) buraya sorar. auth-service:
//  1. dış access token'ı Keycloak'ta introspect eder (aktif mi, oturum iptal edilmiş mi, hangi client'ın, hangi rollerle),
//  2. kanal kurallarını uygular (kanal, gateway'in eklediği x-auth-channel header'ından gelir; istemci değiştiremez):
//     client ↔ kanal, partner sertifikası ↔ client, şube cihaz sertifikası,
//  3. iç JWT'yi Keycloak'tan RFC 8693 token exchange ile alır ve x-user-jwt olarak döner.
//
// İç JWT'yi Keycloak imzalar (kanal başına exchange client'ı: ömür 2 dk, channel claim'i); DMZ'de imza anahtarı yoktur.
// Dış token DMZ'de kalır (gateway Authorization'ı siler); internal servisler yalnızca iç JWT'yi görür.
// Yalnızca standart kütüphane kullanır.
package main

import (
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/url"
	"os"
	"slices"
	"strings"
	"sync"
	"time"
)

var version = "dev" // build sırasında -ldflags ile verilir

// Kanal kuralları: hangi realm, hangi exchange client'ı, hangi dış client'ın (azp) token'ı, hangi rollerle
type channelRule struct {
	realm    string
	exchange string   // Keycloak'ta bu kanalın exchange client'ı (channel claim'ini o ekler)
	clients  []string // boşsa: partner kanalı, azp == sertifika CN'i (x-partner-id)
	roles    []string // en az biri gerekli
}

var rules = map[string]channelRule{
	"web":     {realm: "customers", exchange: "auth-web", clients: []string{"web-app"}, roles: []string{"customer"}},
	"mobile":  {realm: "customers", exchange: "auth-mobile", clients: []string{"mobile-app"}, roles: []string{"customer"}},
	"partner": {realm: "partners", exchange: "auth-partner", roles: []string{"partner"}},
	"branch":  {realm: "staff", exchange: "auth-branch", clients: []string{"branch-teller"}, roles: []string{"teller", "operations"}},
}

const (
	grantTokenExchange = "urn:ietf:params:oauth:grant-type:token-exchange"
	tokenTypeAccess    = "urn:ietf:params:oauth:token-type:access_token"
	cacheTTL           = 30 * time.Second // oturum iptali en geç bu sürede etkili olur
)

type config struct {
	issuerBase  string            // token'ların issuer öneki: https://sso.../realms/
	idpBase     string            // Keycloak'ın mesh içi adresi: http://keycloak.auth.svc.cluster.local/realms/
	internalAud string            // iç JWT'nin audience'ı
	secrets     map[string]string // exchange client -> secret
}

func main() {
	cfg := &config{
		issuerBase:  env("ISSUER_BASE", "https://sso.apps.example.local:8443/realms/"),
		idpBase:     env("IDP_BASE", "http://keycloak.auth.svc.cluster.local/realms/"),
		internalAud: env("INTERNAL_AUDIENCE", "internal-apis"),
		secrets:     map[string]string{},
	}
	for _, r := range rules {
		s := os.Getenv(strings.ToUpper(strings.ReplaceAll(r.exchange, "-", "_")) + "_SECRET") // auth-web -> AUTH_WEB_SECRET
		if s == "" {
			log.Fatalf("%s için secret yok", r.exchange)
		}
		cfg.secrets[r.exchange] = s
	}
	a := &authz{cfg: cfg, client: &http.Client{Timeout: 2 * time.Second}, cache: map[string]cached{}, inflight: map[string]*call{}} // iki çağrı, ext_authz süresi 4 sn
	go a.evictLoop()

	srv := &http.Server{
		Addr:              ":" + env("PORT", "8080"),
		Handler:           a,
		ReadHeaderTimeout: 2 * time.Second,
		ReadTimeout:       5 * time.Second,
		WriteTimeout:      10 * time.Second,
		MaxHeaderBytes:    64 << 10,
	}
	log.Printf("auth-service %s dinliyor: %s (IdP %s, audience %s)", version, srv.Addr, cfg.idpBase, cfg.internalAud)
	log.Fatal(srv.ListenAndServe())
}

type cached struct {
	jwt string
	exp time.Time
}

type authz struct {
	cfg      *config
	client   *http.Client
	mu       sync.Mutex
	cache    map[string]cached // dış token (+ kanal bağlamı) -> iç JWT
	inflight map[string]*call  // aynı anahtar için süren IdP çağrısı (singleflight)
}

// call: aynı token'la eşzamanlı gelen istekler tek introspection + exchange'i bekler (IdP'ye yük patlaması olmaz)
type call struct {
	wg       sync.WaitGroup
	jwt, sub string
	err      error
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
	if c, hit := a.cache[ck]; hit && time.Now().Before(c.exp) {
		a.mu.Unlock()
		return c.jwt, "(önbellek)", nil
	}
	if f, ok := a.inflight[ck]; ok {
		a.mu.Unlock()
		f.wg.Wait()
		return f.jwt, f.sub, f.err
	}
	f := &call{}
	f.wg.Add(1)
	a.inflight[ck] = f
	a.mu.Unlock()

	f.jwt, f.sub, f.err = a.resolve(rule, channel, token, partnerID, device, ck)
	a.mu.Lock()
	delete(a.inflight, ck)
	a.mu.Unlock()
	f.wg.Done()
	return f.jwt, f.sub, f.err
}

// resolve: önbellekte olmayan token için introspection, kanal kuralları ve token exchange
func (a *authz) resolve(rule channelRule, channel, token, partnerID, device, ck string) (string, string, error) {
	// Ön kontrol (imzasız okuma, yalnızca reddetmek için): başka realm'in token'ı IdP'ye hiç gönderilmez
	var unverified map[string]any
	if decodeSegment(segment(token, 1), &unverified) != nil {
		return "", "", deny(http.StatusUnauthorized, "invalid_token", "JWT biçimi değil")
	}
	if iss, _ := unverified["iss"].(string); iss != a.cfg.issuerBase+rule.realm {
		return "", "", deny(http.StatusForbidden, "wrong_realm_for_channel", "iss="+iss)
	}

	// 1. Introspection: imza, süre ve oturumun hâlâ açık olduğu IdP'de kontrol edilir (dış token opak sayılır)
	claims, err := a.introspect(rule, token)
	if err != nil {
		return "", "", err
	}
	if active, _ := claims["active"].(bool); !active {
		return "", "", deny(http.StatusUnauthorized, "invalid_token", "aktif değil (süresi dolmuş, iptal edilmiş ya da geçersiz)")
	}
	if iss, _ := claims["iss"].(string); iss != a.cfg.issuerBase+rule.realm {
		return "", "", deny(http.StatusForbidden, "wrong_realm_for_channel", "iss="+iss)
	}
	if typ, _ := claims["typ"].(string); typ != "Bearer" {
		return "", "", deny(http.StatusUnauthorized, "invalid_token", "access token değil: "+typ)
	}

	// 2. Kanal kuralları
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
	if len(intersect(realmRoles(claims), rule.roles)) == 0 {
		return "", "", deny(http.StatusForbidden, "insufficient_role", fmt.Sprint(realmRoles(claims)))
	}

	// 3. Token exchange: iç JWT'yi Keycloak üretir ve imzalar
	jwt, err := a.exchange(rule, token)
	if err != nil {
		return "", "", err
	}
	var internal map[string]any
	if err := decodeSegment(segment(jwt, 1), &internal); err != nil {
		return "", "", fmt.Errorf("iç JWT çözülemedi: %w", err)
	}
	if ch, _ := internal["channel"].(string); ch != channel {
		return "", "", fmt.Errorf("iç JWT kanalı %q, beklenen %q", ch, channel)
	}
	// Şube: cihaz sertifikası personelin şubesine ait olmalı (branch_id, IdP'deki grup attribute'u)
	if channel == "branch" {
		if b, _ := internal["branch_id"].(string); b != device {
			return "", "", deny(http.StatusForbidden, "device_not_in_staff_branch", fmt.Sprintf("cihaz=%q şube=%q", device, b))
		}
	}

	sub, _ := internal["sub"].(string)
	exp := time.Now().Add(cacheTTL)
	if te := numericTime(internal["exp"]).Add(-10 * time.Second); te.Before(exp) {
		exp = te
	}
	a.mu.Lock()
	if len(a.cache) < 10000 {
		a.cache[ck] = cached{jwt, exp}
	}
	a.mu.Unlock()
	return jwt, sub, nil
}

// introspect: RFC 7662; kanalın exchange client'ının kimliğiyle
func (a *authz) introspect(rule channelRule, token string) (map[string]any, error) {
	var out map[string]any
	status, err := a.post(rule, "/protocol/openid-connect/token/introspect", url.Values{"token": {token}}, &out)
	if err != nil {
		return nil, err
	}
	if status != http.StatusOK {
		return nil, fmt.Errorf("introspection: HTTP %d", status)
	}
	return out, nil
}

// exchange: RFC 8693; dış access token -> iç JWT (aud=internal-apis)
func (a *authz) exchange(rule channelRule, token string) (string, error) {
	var out struct {
		AccessToken string `json:"access_token"`
		Error       string `json:"error"`
		Description string `json:"error_description"`
	}
	status, err := a.post(rule, "/protocol/openid-connect/token", url.Values{
		"grant_type":           {grantTokenExchange},
		"subject_token":        {token},
		"subject_token_type":   {tokenTypeAccess},
		"requested_token_type": {tokenTypeAccess},
		"audience":             {a.cfg.internalAud},
	}, &out)
	switch {
	case err != nil:
		return "", err
	case status == http.StatusOK && out.AccessToken != "":
		return out.AccessToken, nil
	case status == http.StatusBadRequest || status == http.StatusForbidden || status == http.StatusUnauthorized:
		return "", deny(http.StatusForbidden, "exchange_denied", out.Error+": "+out.Description)
	default:
		return "", fmt.Errorf("token exchange: HTTP %d %s", status, out.Error)
	}
}

func (a *authz) post(rule channelRule, path string, form url.Values, out any) (int, error) {
	req, err := http.NewRequest(http.MethodPost, a.cfg.idpBase+rule.realm+path, strings.NewReader(form.Encode()))
	if err != nil {
		return 0, err
	}
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	req.SetBasicAuth(url.QueryEscape(rule.exchange), url.QueryEscape(a.cfg.secrets[rule.exchange]))
	resp, err := a.client.Do(req)
	if err != nil {
		return 0, err
	}
	defer resp.Body.Close()
	if err := json.NewDecoder(io.LimitReader(resp.Body, 1<<20)).Decode(out); err != nil && resp.StatusCode == http.StatusOK {
		return resp.StatusCode, err
	}
	return resp.StatusCode, nil
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

// --- yardımcılar ---

func segment(jwt string, i int) string {
	parts := strings.Split(jwt, ".")
	if len(parts) != 3 {
		return ""
	}
	return parts[i]
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

func env(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}
