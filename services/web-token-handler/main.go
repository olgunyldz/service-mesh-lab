// web-token-handler: web kanalının DMZ bileşeni (OAuth "token handler" / BFF-for-tokens deseni).
//
// Tarayıcı hiç token görmez; elinde yalnızca __Host-sid oturum cookie'si vardır (HttpOnly, Secure, SameSite=Strict).
//
//	/healthz        -> kendi sağlık kontrolü
//	/               -> küçük statik sayfa (lab'de web-static yerine)
//	/auth/login     -> Keycloak'a yönlendirir (Authorization Code + PKCE, state, nonce); ?acr=2: step-up (OTP)
//	/auth/callback  -> code'u sunucu tarafında token'a çevirir (gizli client), oturumu açar, cookie'yi yazar
//	/auth/session   -> oturum durumu ve CSRF token'ı (SPA için)
//	/auth/logout    -> IdP oturumunu da kapatır (POST, CSRF)
//	/api/*          -> cookie -> oturum -> (gerekirse refresh) -> auth-service (introspection + token exchange)
//	                   -> iç JWT ile internal'daki web-bff'e (DMZ egress üzerinden)
//
// Token'lar oturum deposunda (Valkey, mgmt; yalnızca sess:* anahtarları) durur. İş mantığı yok.
// Yalnızca standart kütüphane kullanır.
package main

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"strings"
	"sync"
	"time"
)

var version = "dev" // build sırasında -ldflags ile verilir

const (
	sessionCookie = "__Host-sid"
	loginCookie   = "__Host-login"
)

type config struct {
	publicURL    string // https://www.apps.example.local:8443 (redirect_uri bunun altında)
	issuer       string // tarayıcının gördüğü IdP adresi (authorize, logout)
	idpBase      string // IdP'nin mesh içi adresi (token uçları; DMZ egress üzerinden)
	clientID     string
	clientSecret string
	authzURL     string // auth-service (ext_authz)
	bffURL       *url.URL
	idle         time.Duration
	absolute     time.Duration
}

type session struct {
	AccessToken  string    `json:"at"`
	RefreshToken string    `json:"rt"`
	IDToken      string    `json:"it"`
	AccessExp    time.Time `json:"ae"`
	Created      time.Time `json:"c"`
	CSRF         string    `json:"x"`
	Sub          string    `json:"s"`
}

type loginState struct {
	Verifier string `json:"v"`
	Nonce    string `json:"n"`
}

type handler struct {
	cfg    *config
	store  *valkey
	client *http.Client
	proxy  *httputil.ReverseProxy
	locks  sync.Map // oturum başına kilit: aynı refresh token iki kez kullanılmasın (rotation + tekrar kullanım tespiti)
}

func main() {
	bff, err := url.Parse(env("BFF_URL", "http://web-bff.edge-web.svc.cluster.local"))
	if err != nil {
		log.Fatalf("BFF_URL: %v", err)
	}
	cfg := &config{
		publicURL:    env("PUBLIC_URL", "https://www.apps.example.local:8443"),
		issuer:       env("ISSUER", "https://sso.apps.example.local:8443/realms/customers"),
		idpBase:      env("IDP_BASE", "http://keycloak.edge-web.svc.cluster.local/realms/customers"),
		clientID:     env("CLIENT_ID", "web-app"),
		clientSecret: os.Getenv("CLIENT_SECRET"),
		authzURL:     env("AUTHZ_URL", "http://auth-service.auth.svc.cluster.local:8080"),
		bffURL:       bff,
		idle:         15 * time.Minute,
		absolute:     8 * time.Hour,
	}
	if cfg.clientSecret == "" {
		log.Fatal("CLIENT_SECRET yok")
	}
	h := &handler{
		cfg:    cfg,
		store:  &valkey{addr: env("VALKEY_ADDR", "valkey.edge-web.svc.cluster.local:6379"), user: os.Getenv("VALKEY_USER"), pass: os.Getenv("VALKEY_PASSWORD")},
		client: &http.Client{Timeout: 5 * time.Second},
	}
	h.proxy = &httputil.ReverseProxy{Rewrite: h.rewrite, ErrorHandler: func(w http.ResponseWriter, r *http.Request, err error) {
		log.Printf("BFF hatası: %s %s: %v", r.Method, r.URL.Path, err)
		writeJSON(w, http.StatusBadGateway, map[string]string{"error": "upstream_unavailable"})
	}}

	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, _ *http.Request) { writeJSON(w, http.StatusOK, map[string]string{"status": "ok"}) })
	mux.HandleFunc("GET /{$}", index)
	mux.HandleFunc("GET /auth/login", h.login)
	mux.HandleFunc("GET /auth/callback", h.callback)
	mux.HandleFunc("GET /auth/session", h.sessionInfo)
	mux.HandleFunc("POST /auth/logout", h.logout)
	mux.HandleFunc("/api/", h.api)

	srv := &http.Server{
		Addr:              ":" + env("PORT", "8080"),
		Handler:           securityHeaders(mux),
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       15 * time.Second,
		WriteTimeout:      20 * time.Second,
		MaxHeaderBytes:    32 << 10,
	}
	log.Printf("web-token-handler %s dinliyor: %s (IdP %s, BFF %s)", version, srv.Addr, cfg.issuer, cfg.bffURL)
	log.Fatal(srv.ListenAndServe())
}

// --- giriş ---

func (h *handler) login(w http.ResponseWriter, r *http.Request) {
	state, verifier, nonce := randomToken(), randomToken(), randomToken()
	if err := h.store.setJSON("sess:login:"+hash(state), loginState{verifier, nonce}, 5*time.Minute); err != nil {
		h.fail(w, "oturum deposu", err)
		return
	}
	challenge := sha256.Sum256([]byte(verifier))
	q := url.Values{
		"response_type":         {"code"},
		"client_id":             {h.cfg.clientID},
		"redirect_uri":          {h.cfg.publicURL + "/auth/callback"},
		"scope":                 {"openid"},
		"state":                 {state},
		"nonce":                 {nonce},
		"code_challenge":        {base64.RawURLEncoding.EncodeToString(challenge[:])},
		"code_challenge_method": {"S256"},
	}
	// Step-up (09b): daha yüksek doğrulama seviyesi. IdP'de açık oturum varsa yalnızca eksik adım (OTP) sorulur.
	if r.URL.Query().Get("acr") == "2" {
		q.Set("acr_values", "2")
	}
	// state'i bu tarayıcıya bağlar (login CSRF): callback'teki state cookie'dekiyle aynı olmalı.
	// Lax: IdP'den dönüş üst seviye bir yönlendirme; Strict'te cookie gelmeyebilir.
	http.SetCookie(w, &http.Cookie{Name: loginCookie, Value: state, Path: "/", MaxAge: 300, HttpOnly: true, Secure: true, SameSite: http.SameSiteLaxMode})
	http.Redirect(w, r, h.cfg.issuer+"/protocol/openid-connect/auth?"+q.Encode(), http.StatusFound)
}

func (h *handler) callback(w http.ResponseWriter, r *http.Request) {
	state, code := r.URL.Query().Get("state"), r.URL.Query().Get("code")
	c, err := r.Cookie(loginCookie)
	if state == "" || code == "" || err != nil || subtle.ConstantTimeCompare([]byte(c.Value), []byte(state)) != 1 {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid_state"})
		return
	}
	var ls loginState
	key := "sess:login:" + hash(state)
	if ok, err := h.store.getJSON(key, &ls); err != nil || !ok {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid_state"})
		return
	}
	h.store.del(key) // state tek kullanımlık

	tok, err := h.tokenRequest(url.Values{
		"grant_type":    {"authorization_code"},
		"code":          {code},
		"redirect_uri":  {h.cfg.publicURL + "/auth/callback"},
		"code_verifier": {ls.Verifier},
	})
	if err != nil {
		log.Printf("code değişimi başarısız: %v", err)
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "login_failed"})
		return
	}
	// id_token IdP'den doğrudan (mTLS, arka kanal) geldiği için imzası ayrıca doğrulanmaz; nonce kontrol edilir
	var idc map[string]any
	if decodeSegment(segment(tok.IDToken, 1), &idc) != nil || idc["nonce"] != ls.Nonce {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "invalid_nonce"})
		return
	}
	sid := randomToken()
	sub, _ := idc["sub"].(string)
	s := &session{AccessToken: tok.AccessToken, RefreshToken: tok.RefreshToken, IDToken: tok.IDToken,
		AccessExp: time.Now().Add(time.Duration(tok.ExpiresIn) * time.Second), Created: time.Now(), CSRF: randomToken(), Sub: sub}
	if err := h.save(sid, s); err != nil {
		h.fail(w, "oturum deposu", err)
		return
	}
	log.Printf("oturum açıldı sub=%s", sub)
	http.SetCookie(w, &http.Cookie{Name: loginCookie, Value: "", Path: "/", MaxAge: -1, HttpOnly: true, Secure: true, SameSite: http.SameSiteLaxMode})
	http.SetCookie(w, &http.Cookie{Name: sessionCookie, Value: sid, Path: "/", HttpOnly: true, Secure: true, SameSite: http.SameSiteStrictMode})
	http.Redirect(w, r, "/", http.StatusFound)
}

func (h *handler) sessionInfo(w http.ResponseWriter, r *http.Request) {
	_, s, err := h.load(r)
	if err != nil || s == nil {
		writeJSON(w, http.StatusUnauthorized, map[string]any{"authenticated": false})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"authenticated": true, "csrf": s.CSRF, "absolute_expiry": s.Created.Add(h.cfg.absolute).Unix()})
}

func (h *handler) logout(w http.ResponseWriter, r *http.Request) {
	sid, s, err := h.load(r)
	if err != nil || s == nil {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "login_required"})
		return
	}
	if !validCSRF(r, s) {
		writeJSON(w, http.StatusForbidden, map[string]string{"error": "csrf"})
		return
	}
	// IdP oturumunu da kapat (arka kanal); refresh token ve oturuma bağlı tüm token'lar geçersizleşir
	if err := h.idpPost("/protocol/openid-connect/logout", url.Values{"refresh_token": {s.RefreshToken}}, nil); err != nil {
		log.Printf("IdP logout: %v", err)
	}
	h.store.del("sess:" + hash(sid))
	log.Printf("oturum kapandı sub=%s", s.Sub)
	http.SetCookie(w, &http.Cookie{Name: sessionCookie, Value: "", Path: "/", MaxAge: -1, HttpOnly: true, Secure: true, SameSite: http.SameSiteStrictMode})
	w.WriteHeader(http.StatusNoContent)
}

// --- API: cookie -> iç JWT -> BFF ---

func (h *handler) api(w http.ResponseWriter, r *http.Request) {
	sid, s, err := h.load(r)
	if err != nil {
		h.fail(w, "oturum deposu", err)
		return
	}
	if s == nil {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "login_required"})
		return
	}
	if r.Method != http.MethodGet && r.Method != http.MethodHead && !validCSRF(r, s) {
		writeJSON(w, http.StatusForbidden, map[string]string{"error": "csrf"})
		return
	}
	if time.Until(s.AccessExp) < 30*time.Second {
		if s, err = h.refresh(sid, s); err != nil {
			log.Printf("refresh başarısız sub=%s: %v", s.Sub, err)
			h.store.del("sess:" + hash(sid))
			writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "login_required"})
			return
		}
	} else if err := h.save(sid, s); err != nil { // idle süresini uzatır
		h.fail(w, "oturum deposu", err)
		return
	}

	jwt, status, err := h.internalJWT(r, s.AccessToken)
	if err != nil {
		h.fail(w, "auth-service", err)
		return
	}
	if status != http.StatusOK {
		writeJSON(w, status, map[string]string{"error": "access_denied"})
		return
	}
	r = r.WithContext(context.WithValue(r.Context(), jwtKey{}, jwt))
	h.proxy.ServeHTTP(w, r)
}

type jwtKey struct{}

// rewrite: /api/x -> BFF /x. Yalnızca izinli header'lar geçer (cookie, Authorization, sahte x-user-jwt / XFF geçmez).
func (h *handler) rewrite(pr *httputil.ProxyRequest) {
	in := pr.In
	pr.SetURL(h.cfg.bffURL)
	pr.Out.URL.Path = strings.TrimPrefix(in.URL.Path, "/api")
	pr.Out.URL.RawPath = ""
	pr.Out.Host = ""
	pr.Out.Header = http.Header{}
	for _, k := range []string{"Accept", "Accept-Language", "Content-Type", "Content-Length", "User-Agent", "X-Request-Id", "Traceparent", "Tracestate"} {
		if v := in.Header.Values(k); len(v) > 0 {
			pr.Out.Header[k] = v
		}
	}
	pr.Out.Header.Set("x-user-jwt", in.Context().Value(jwtKey{}).(string))
	pr.Out.Header.Set("x-channel", "web")
}

// internalJWT: auth-service'e ext_authz kontrolü gibi sorar (kanal: web)
func (h *handler) internalJWT(r *http.Request, accessToken string) (string, int, error) {
	req, err := http.NewRequestWithContext(r.Context(), r.Method, h.cfg.authzURL+r.URL.Path, nil)
	if err != nil {
		return "", 0, err
	}
	req.Header.Set("Authorization", "Bearer "+accessToken)
	req.Header.Set("x-auth-channel", "web")
	if id := r.Header.Get("x-request-id"); id != "" {
		req.Header.Set("x-request-id", id)
	}
	resp, err := h.client.Do(req)
	if err != nil {
		return "", 0, err
	}
	defer resp.Body.Close()
	io.Copy(io.Discard, resp.Body)
	if resp.StatusCode == http.StatusOK {
		return resp.Header.Get("x-user-jwt"), http.StatusOK, nil
	}
	if resp.StatusCode >= 500 {
		return "", 0, fmt.Errorf("auth-service HTTP %d", resp.StatusCode)
	}
	return "", resp.StatusCode, nil
}

// refresh: access token'ı yeniler. Refresh token her kullanımda yenilenir (rotation); eski token tekrar kullanılamaz.
func (h *handler) refresh(sid string, s *session) (*session, error) {
	mu, _ := h.locks.LoadOrStore(sid, &sync.Mutex{})
	mu.(*sync.Mutex).Lock()
	defer mu.(*sync.Mutex).Unlock()
	defer h.locks.Delete(sid)
	var cur session // başka bir istek az önce yenilemiş olabilir
	if ok, err := h.store.getJSON("sess:"+hash(sid), &cur); err == nil && ok && time.Until(cur.AccessExp) >= 30*time.Second {
		return &cur, nil
	}
	tok, err := h.tokenRequest(url.Values{"grant_type": {"refresh_token"}, "refresh_token": {s.RefreshToken}})
	if err != nil {
		return s, err
	}
	s.AccessToken, s.AccessExp = tok.AccessToken, time.Now().Add(time.Duration(tok.ExpiresIn)*time.Second)
	if tok.RefreshToken != "" {
		s.RefreshToken = tok.RefreshToken
	}
	return s, h.save(sid, s)
}

// --- oturum deposu ---

func (h *handler) load(r *http.Request) (string, *session, error) {
	c, err := r.Cookie(sessionCookie)
	if err != nil || len(c.Value) < 32 {
		return "", nil, nil
	}
	var s session
	ok, err := h.store.getJSON("sess:"+hash(c.Value), &s)
	if err != nil || !ok {
		return "", nil, err
	}
	if time.Since(s.Created) > h.cfg.absolute { // absolute timeout: idle'dan bağımsız
		h.store.del("sess:" + hash(c.Value))
		return "", nil, nil
	}
	return c.Value, &s, nil
}

// save: anahtar cookie değerinin hash'i (depo sızsa bile cookie elde edilemez); TTL = idle timeout
func (h *handler) save(sid string, s *session) error {
	return h.store.setJSON("sess:"+hash(sid), s, h.cfg.idle)
}

// --- IdP ---

type tokenResponse struct {
	AccessToken  string `json:"access_token"`
	RefreshToken string `json:"refresh_token"`
	IDToken      string `json:"id_token"`
	ExpiresIn    int    `json:"expires_in"`
}

func (h *handler) tokenRequest(form url.Values) (*tokenResponse, error) {
	var t tokenResponse
	if err := h.idpPost("/protocol/openid-connect/token", form, &t); err != nil {
		return nil, err
	}
	if t.AccessToken == "" {
		return nil, errors.New("yanıtta access_token yok")
	}
	return &t, nil
}

func (h *handler) idpPost(path string, form url.Values, out any) error {
	req, err := http.NewRequest(http.MethodPost, h.cfg.idpBase+path, strings.NewReader(form.Encode()))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	req.SetBasicAuth(url.QueryEscape(h.cfg.clientID), url.QueryEscape(h.cfg.clientSecret))
	resp, err := h.client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if resp.StatusCode >= 300 {
		return fmt.Errorf("HTTP %d: %.200s", resp.StatusCode, body)
	}
	if out != nil {
		return json.Unmarshal(body, out)
	}
	return nil
}

// --- yardımcılar ---

func (h *handler) fail(w http.ResponseWriter, what string, err error) {
	log.Printf("%s: %v", what, err)
	writeJSON(w, http.StatusServiceUnavailable, map[string]string{"error": "unavailable"})
}

func validCSRF(r *http.Request, s *session) bool {
	v := r.Header.Get("X-CSRF-Token")
	return v != "" && subtle.ConstantTimeCompare([]byte(v), []byte(s.CSRF)) == 1
}

func index(w http.ResponseWriter, _ *http.Request) {
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	io.WriteString(w, `<!doctype html><html lang="tr"><head><meta charset="utf-8"><title>İnternet şubesi (lab)</title></head>`+
		`<body><h1>İnternet şubesi (lab)</h1><p><a href="/auth/login">Giriş</a> · <a href="/api/bff/v1/dashboard">Özet</a></p></body></html>`)
}

// Tarayıcı kanalına özel güvenlik header'ları; kimlik ve API yanıtları önbelleğe alınmaz
func securityHeaders(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hd := w.Header()
		hd.Set("X-Content-Type-Options", "nosniff")
		hd.Set("X-Frame-Options", "DENY")
		hd.Set("Referrer-Policy", "no-referrer")
		hd.Set("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'; form-action 'self'")
		hd.Set("Cache-Control", "no-store")
		next.ServeHTTP(w, r)
	})
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(v)
}

func randomToken() string {
	b := make([]byte, 32)
	rand.Read(b)
	return base64.RawURLEncoding.EncodeToString(b)
}

func hash(s string) string {
	h := sha256.Sum256([]byte(s))
	return hex.EncodeToString(h[:])
}

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

func env(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}
