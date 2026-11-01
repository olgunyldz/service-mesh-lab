// mobile-bff: mobil kanalın arka ucu (Backend for Frontend). Internal'da (cluster-a, ns channel-bff) çalışır (09c).
//
//	/healthz                    -> kendi sağlık kontrolü
//	POST   /devices             -> cihaz kaydı: seviye 2 (son 5 dk), DPoP kanıtı (cihaz anahtarı) ve attestation;
//	                               device-registry'ye (mgmt) yazılır
//	GET    /devices             -> kullanıcının cihazları
//	DELETE /devices/{id}        -> cihaz kaydını siler (kayıp / çalınan telefon)
//	POST   /accounts/{id}/transfers -> seviye 2 kontrolü (step-up ipucu), sonra account-api
//	/accounts*, /products       -> account-api
//	diğer her yol               -> api-a
//
// Önündeki zincir: mobil uygulama -> edge -> mobile-gateway (ext_authz: DPoP, attestation, kayıtlı cihaz, iç JWT)
// -> DMZ egress -> int-ingressgw -> mobile-bff. Kullanıcı (sub) ve doğrulama seviyesi (loa_map) IdP imzalı iç JWT'den.
package main

import (
	"bytes"
	"crypto/ecdsa"
	"crypto/x509"
	"encoding/base64"
	"encoding/json"
	"encoding/pem"
	"errors"
	"io"
	"log"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"strings"
	"time"
)

var version = "dev" // build sırasında -ldflags ile verilir

type config struct {
	registry   string           // device-registry (mesh içi ad; waypoint -> cluster-a egress -> mgmt)
	publicBase string           // DPoP htu öneki (istemcinin gördüğü adres + /mobile/v1)
	appID      string
	attestPub  *ecdsa.PublicKey
	client     *http.Client
}

func main() {
	api := mustURL(env("API_URL", "http://api-a.api-a.svc.cluster.local"))
	accounts := mustURL(env("ACCOUNTS_URL", "http://account-api.account-api.svc.cluster.local:8080"))
	pub, err := loadECPublicKey(env("ATTEST_PUBLIC_KEY", "/attest/attest.pub"))
	if err != nil {
		log.Fatalf("attestation açık anahtarı: %v", err)
	}
	cfg := &config{
		registry:   env("REGISTRY_URL", "http://device-registry.channel-bff.svc.cluster.local"),
		publicBase: env("PUBLIC_BASE", "https://mobile-api.apps.example.local:8443/mobile/v1"),
		appID:      env("APP_ID", "tr.com.example.bank"),
		attestPub:  pub,
		client:     &http.Client{Timeout: 5 * time.Second},
	}

	accountsProxy := reverseProxy(accounts)
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, _ *http.Request) { writeJSON(w, http.StatusOK, map[string]string{"status": "ok"}) })
	mux.HandleFunc("POST /devices", cfg.registerDevice)
	mux.HandleFunc("GET /devices", cfg.listDevices)
	mux.HandleFunc("DELETE /devices/{id}", cfg.deleteDevice)
	mux.Handle("POST /accounts/{id}/transfers", requireLevel("2", 5*time.Minute, accountsProxy))
	mux.Handle("/accounts", accountsProxy)
	mux.Handle("/accounts/", accountsProxy)
	mux.Handle("/products", accountsProxy)
	mux.Handle("/", reverseProxy(api))

	srv := &http.Server{
		Addr:              ":" + env("PORT", "8080"),
		Handler:           mux,
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       10 * time.Second,
		WriteTimeout:      15 * time.Second,
		MaxHeaderBytes:    32 << 10,
	}
	log.Printf("mobile-bff %s dinliyor: %s (api %s, hesaplar %s, cihazlar %s)", version, srv.Addr, api, accounts, cfg.registry)
	log.Fatal(srv.ListenAndServe())
}

// registerDevice: cihazın public key'ini kullanıcıya bağlar. Kanıtlar burada yeniden doğrulanır (DMZ'ye güvenilmez):
// iç JWT (sub, seviye 2 son 5 dk) IdP imzalı; DPoP kanıtı anahtarın sahibinin bu cihaz olduğunu, attestation
// uygulamanın gerçek ve bu anahtara bağlı olduğunu gösterir.
func (c *config) registerDevice(w http.ResponseWriter, r *http.Request) {
	u := userFrom(r)
	if !u.levelFresh("2", 5*time.Minute) {
		stepUp(w, "2")
		return
	}
	proof, err := verifyDPoP(r.Header.Get("DPoP"), http.MethodPost, c.publicBase+"/devices", "", 60*time.Second)
	if err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid_dpop_proof"})
		return
	}
	att, err := verifyAttestation(r.Header.Get("x-app-attestation"), c.attestPub, c.appID, "0", proof.jkt)
	if err != nil {
		writeJSON(w, http.StatusForbidden, map[string]string{"error": "attestation_failed"})
		return
	}
	var req struct {
		Name string `json:"name"`
	}
	json.NewDecoder(io.LimitReader(r.Body, 4<<10)).Decode(&req)
	body, _ := json.Marshal(map[string]any{"sub": u.Sub, "jkt": proof.jkt, "jwk": proof.jwk, "app_id": att.appID,
		"app_version": att.version, "name": req.Name})
	c.forward(w, r, http.MethodPost, "/v1/devices", body)
}

func (c *config) listDevices(w http.ResponseWriter, r *http.Request) {
	c.forward(w, r, http.MethodGet, "/v1/devices?"+url.Values{"sub": {userFrom(r).Sub}}.Encode(), nil)
}

func (c *config) deleteDevice(w http.ResponseWriter, r *http.Request) {
	c.forward(w, r, http.MethodDelete, "/v1/devices/"+url.PathEscape(r.PathValue("id"))+"?"+url.Values{"sub": {userFrom(r).Sub}}.Encode(), nil)
}

// forward: device-registry'ye çağrı; sub her zaman iç JWT'den (istemci başka kullanıcının cihazına dokunamaz)
func (c *config) forward(w http.ResponseWriter, r *http.Request, method, path string, body []byte) {
	if userFrom(r).Sub == "" {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "missing_identity"})
		return
	}
	req, _ := http.NewRequestWithContext(r.Context(), method, c.registry+path, bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("x-request-id", r.Header.Get("x-request-id"))
	resp, err := c.client.Do(req)
	if err != nil {
		log.Printf("device-registry: %v", err)
		writeJSON(w, http.StatusBadGateway, map[string]string{"error": "upstream_unavailable"})
		return
	}
	defer resp.Body.Close()
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(resp.StatusCode)
	io.Copy(w, io.LimitReader(resp.Body, 64<<10))
}

type user struct {
	Sub    string `json:"sub"`
	LoaMap string `json:"loa_map"`
}

// userFrom: x-user-jwt payload'u (imza mesh'te doğrulandı)
func userFrom(r *http.Request) user {
	var u user
	if parts := strings.Split(r.Header.Get("x-user-jwt"), "."); len(parts) == 3 {
		if b, err := base64.RawURLEncoding.DecodeString(parts[1]); err == nil {
			json.Unmarshal(b, &u)
		}
	}
	return u
}

// levelFresh: bu oturumda en az bu seviyeyle, en fazla maxAge önce doğrulandı mı (loa_map, IdP imzalı)
func (u user) levelFresh(level string, maxAge time.Duration) bool {
	var m map[string]int64
	if json.Unmarshal([]byte(u.LoaMap), &m) != nil {
		return false
	}
	t, ok := m[level]
	return ok && time.Since(time.Unix(t, 0)) <= maxAge
}

func stepUp(w http.ResponseWriter, level string) {
	w.Header().Set("WWW-Authenticate", `DPoP error="insufficient_user_authentication", acr_values="`+level+`"`)
	writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "insufficient_user_authentication", "acr_values": level})
}

// requireLevel: işlem için gereken doğrulama seviyesi yoksa step-up ipucu (RFC 9470); asıl karar domain servisinde
func requireLevel(level string, maxAge time.Duration, next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if !userFrom(r).levelFresh(level, maxAge) {
			stepUp(w, level)
			return
		}
		next.ServeHTTP(w, r)
	})
}

func reverseProxy(target *url.URL) *httputil.ReverseProxy {
	p := httputil.NewSingleHostReverseProxy(target)
	// Hata ayrıntısı (iç adres, bağlantı hatası) istemciye dönmesin
	p.ErrorHandler = func(w http.ResponseWriter, r *http.Request, err error) {
		log.Printf("upstream hatası: %s %s: %v", r.Method, r.URL.Path, err)
		writeJSON(w, http.StatusBadGateway, map[string]string{"error": "upstream_unavailable"})
	}
	return p
}

func loadECPublicKey(path string) (*ecdsa.PublicKey, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	blk, _ := pem.Decode(b)
	if blk == nil {
		return nil, errors.New("PEM değil")
	}
	k, err := x509.ParsePKIXPublicKey(blk.Bytes)
	if err != nil {
		return nil, err
	}
	pub, ok := k.(*ecdsa.PublicKey)
	if !ok {
		return nil, errors.New("EC anahtarı değil")
	}
	return pub, nil
}

func mustURL(s string) *url.URL {
	u, err := url.Parse(s)
	if err != nil {
		log.Fatalf("adres geçersiz %q: %v", s, err)
	}
	return u
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(v)
}

func env(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}
