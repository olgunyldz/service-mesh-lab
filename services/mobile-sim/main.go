// mobile-sim: mobil uygulama simülatörü (09c · mobile-binding; testler ve yük üretici kullanır). Gerçek bir telefon
// uygulamasının güvenlikle ilgili davranışını taklit eder:
//
//	login [--acr 2]      sistem tarayıcısıyla giriş gibi: Authorization Code + PKCE (mobile-app public client);
//	                     --acr 2: seviye 2 (parola + OTP)
//	bind [ad]            cihaz anahtar çiftini (ECDSA P-256; gerçekte Secure Enclave / StrongBox, dışa aktarılamaz)
//	                     kullanıcıya bağlar: POST /mobile/v1/devices (DPoP kanıtı + attestation)
//	call [curl seçenekleri] YOL
//	                     her isteği "Authorization: DPoP <token>", DPoP kanıtı ve attestation ile gönderir.
//	                     Seçenekler (curl alt kümesi): -X metot, -d gövde, -H başlık, -w '%{http_code}', -o /dev/null, -D -
//	devices | unbind ID  kullanıcının cihazları / cihaz kaydını silme
//	idp-logout           IdP oturumunu kapatır (refresh token ile)
//	daemon               bekler (docker exec ile komut çalıştırmak için)
//	loop                 yük üretici: giriş (seviye 2) + bağlama, ardından saniyede bir hesap sorgusu
//
// Ortam: EDGE_HOST (tüm https istekleri bu adrese gider), SSO, MOBILE (host adları), CA, STATE (durum dizini),
// USERNAME, PASSWORD, OTP_SECRET, ATTEST_KEY (lab attestation sağlayıcısının anahtarı), APP_ID, APP_VERSION.
// Negatif testler için: DEVICE_KEY (başka anahtar dosyası), NO_DPOP=1, NO_ATTEST=1, REPLAY=1 (aynı kanıtı iki kez gönder),
// HTU (kanıttaki adres), SCHEME (Authorization şeması), INTEGRITY (attestation bütünlük sonucu).
package main

import (
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha1"
	"crypto/sha256"
	"crypto/tls"
	"crypto/x509"
	"encoding/base64"
	"encoding/binary"
	"encoding/json"
	"encoding/pem"
	"errors"
	"fmt"
	"html"
	"io"
	"net"
	"net/http"
	"net/http/cookiejar"
	"net/url"
	"os"
	"regexp"
	"sort"
	"strings"
	"time"
)

var version = "dev"

const redirectURI = "tr.com.example.bank:/oauth2redirect"

var (
	sso    = env("SSO", "sso.apps.example.local")
	mobile = env("MOBILE", "mobile-api.apps.example.local")
	state  = env("STATE", "/state")
	b64    = base64.RawURLEncoding
)

var lastStatus int // son call'ın HTTP durumu (loop kullanır)

type tokens struct {
	Access  string `json:"access_token"`
	Refresh string `json:"refresh_token"`
	Expires int64  `json:"expires_at"`
}

func main() {
	if len(os.Args) < 2 {
		fail("komut gerekli (login, bind, call, devices, unbind, idp-logout, daemon, loop)")
	}
	var err error
	switch args := os.Args[2:]; os.Args[1] {
	case "login":
		acr := ""
		if len(args) == 2 && args[0] == "--acr" {
			acr = args[1]
		}
		err = login(acr)
	case "bind":
		name := "lab-telefon"
		if len(args) > 0 {
			name = args[0]
		}
		err = call([]string{"-X", "POST", "-d", `{"name":"` + name + `"}`, "-H", "Content-Type: application/json", "/mobile/v1/devices"})
	case "call":
		err = call(args)
	case "devices":
		err = call([]string{"/mobile/v1/devices"})
	case "unbind":
		err = call([]string{"-X", "DELETE", "-w", "%{http_code}", "-o", "/dev/null", "/mobile/v1/devices/" + args[0]})
	case "idp-logout":
		err = idpLogout()
	case "daemon":
		for { // başka goroutine yok: "select {}" çalışma zamanında deadlock sayılır
			time.Sleep(time.Hour)
		}
	case "loop":
		loop()
	default:
		err = errors.New("bilinmeyen komut: " + os.Args[1])
	}
	if err != nil {
		fail(err.Error())
	}
}

// --- HTTP: tüm https istekleri edge'e (gerçek ağdaki DNS + edge VIP'i gibi) ---

func httpClient(jar http.CookieJar) *http.Client {
	pool := x509.NewCertPool()
	if b, err := os.ReadFile(env("CA", "/ca.pem")); err == nil {
		pool.AppendCertsFromPEM(b)
	}
	edge := env("EDGE_HOST", "edge-lb")
	tr := &http.Transport{
		TLSClientConfig: &tls.Config{RootCAs: pool, MinVersion: tls.VersionTLS12},
		DialContext: func(ctx context.Context, network, addr string) (net.Conn, error) {
			_, port, _ := net.SplitHostPort(addr)
			return (&net.Dialer{Timeout: 5 * time.Second}).DialContext(ctx, network, net.JoinHostPort(edge, port))
		},
	}
	return &http.Client{Transport: tr, Jar: jar, Timeout: 20 * time.Second,
		CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
}

// --- giriş: Authorization Code + PKCE, Keycloak giriş formları (parola, OTP) ---

var actionRe = regexp.MustCompile(`action="([^"]*login-actions/authenticate[^"]*)"`)

func login(acr string) error {
	jar, _ := cookiejar.New(nil)
	c := httpClient(jar)
	verifier, st := random(32), random(16)
	ch := sha256.Sum256([]byte(verifier))
	q := url.Values{"response_type": {"code"}, "client_id": {"mobile-app"}, "redirect_uri": {redirectURI}, "scope": {"openid"},
		"state": {st}, "code_challenge": {b64.EncodeToString(ch[:])}, "code_challenge_method": {"S256"}}
	if acr != "" {
		q.Set("acr_values", acr)
	}
	base := "https://" + sso + ":8443/realms/customers/protocol/openid-connect"
	resp, err := c.Get(base + "/auth?" + q.Encode())
	if err != nil {
		return err
	}
	page, _ := io.ReadAll(resp.Body)
	resp.Body.Close()
	otpSent := false
	for i := 0; i < 4; i++ {
		m := actionRe.FindSubmatch(page)
		if m == nil {
			return fmt.Errorf("giriş formu bulunamadı (HTTP %d)", resp.StatusCode)
		}
		form := url.Values{"username": {env("USERNAME", "ayse")}, "password": {os.Getenv("PASSWORD")}}
		if strings.Contains(string(page), `name="otp"`) {
			if otpSent {
				return errors.New("OTP reddedildi")
			}
			form, otpSent = url.Values{"otp": {totp(os.Getenv("OTP_SECRET"), time.Now())}}, true
		}
		resp, err = c.PostForm(html.UnescapeString(string(m[1])), form)
		if err != nil {
			return err
		}
		page, _ = io.ReadAll(resp.Body)
		resp.Body.Close()
		if loc := resp.Header.Get("Location"); strings.HasPrefix(loc, redirectURI) {
			u, _ := url.Parse(loc)
			if u.Query().Get("state") != st {
				return errors.New("state uyuşmuyor")
			}
			return tokenRequest(c, url.Values{"grant_type": {"authorization_code"}, "client_id": {"mobile-app"},
				"code": {u.Query().Get("code")}, "redirect_uri": {redirectURI}, "code_verifier": {verifier}})
		}
	}
	return errors.New("giriş tamamlanamadı")
}

func tokenRequest(c *http.Client, form url.Values) error {
	resp, err := c.PostForm("https://"+sso+":8443/realms/customers/protocol/openid-connect/token", form)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	var t struct {
		Access    string `json:"access_token"`
		Refresh   string `json:"refresh_token"`
		ExpiresIn int64  `json:"expires_in"`
		Error     string `json:"error_description"`
	}
	json.NewDecoder(resp.Body).Decode(&t)
	if t.Access == "" {
		return fmt.Errorf("token alınamadı: HTTP %d %s", resp.StatusCode, t.Error)
	}
	return save("tokens.json", tokens{t.Access, t.Refresh, time.Now().Unix() + t.ExpiresIn})
}

func currentToken() (string, error) {
	var t tokens
	if err := load("tokens.json", &t); err != nil {
		return "", errors.New("önce login")
	}
	if time.Now().Unix() > t.Expires-30 { // refresh token her kullanımda yenilenir (rotation)
		if err := tokenRequest(httpClient(nil), url.Values{"grant_type": {"refresh_token"}, "client_id": {"mobile-app"},
			"refresh_token": {t.Refresh}}); err != nil {
			return "", err
		}
		load("tokens.json", &t)
	}
	return t.Access, nil
}

func idpLogout() error {
	var t tokens
	if err := load("tokens.json", &t); err != nil {
		return err
	}
	resp, err := httpClient(nil).PostForm("https://"+sso+":8443/realms/customers/protocol/openid-connect/logout",
		url.Values{"client_id": {"mobile-app"}, "refresh_token": {t.Refresh}})
	if err != nil {
		return err
	}
	resp.Body.Close()
	fmt.Println(resp.StatusCode)
	return nil
}

// --- istek: DPoP + attestation ---

func call(args []string) error {
	method, body, outFile, wfmt, dumpHeaders := "GET", "", "", "", false
	var headers []string
	var path string
	for i := 0; i < len(args); i++ {
		switch a := args[i]; a {
		case "-X":
			i++
			method = args[i]
		case "-d":
			i++
			body = args[i]
			if method == "GET" {
				method = "POST"
			}
		case "-H":
			i++
			headers = append(headers, args[i])
		case "-o":
			i++
			outFile = args[i]
		case "-w":
			i++
			wfmt = args[i]
		case "-D":
			i++
			dumpHeaders = args[i] == "-"
		default:
			path = a
		}
	}
	if u, err := url.Parse(path); err == nil && u.Host != "" {
		path = u.RequestURI()
	}
	token, err := currentToken()
	if err != nil {
		return err
	}
	key, err := deviceKey()
	if err != nil {
		return err
	}
	htu := env("HTU", "https://"+mobile+":8443"+strings.SplitN(path, "?", 2)[0])
	proof := dpopProof(key, method, htu, token)
	send := func() (*http.Response, error) {
		req, _ := http.NewRequest(method, "https://"+mobile+":8443"+path, strings.NewReader(body))
		req.Header.Set("Authorization", env("SCHEME", "DPoP")+" "+token)
		if os.Getenv("NO_DPOP") == "" {
			req.Header.Set("DPoP", proof)
		}
		if os.Getenv("NO_ATTEST") == "" {
			req.Header.Set("x-app-attestation", attestation(key))
		}
		for _, h := range headers {
			if k, v, ok := strings.Cut(h, ":"); ok {
				req.Header.Set(strings.TrimSpace(k), strings.TrimSpace(v))
			}
		}
		if body != "" && req.Header.Get("Content-Type") == "" { // curl -d ile aynı varsayılan (WAF içerik tipsiz gövdeyi reddeder)
			req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
		}
		return httpClient(nil).Do(req)
	}
	resp, err := send()
	if err != nil {
		return err
	}
	if os.Getenv("REPLAY") != "" { // aynı kanıt (jti) ikinci kez: reddedilmeli
		io.Copy(io.Discard, resp.Body)
		resp.Body.Close()
		if resp, err = send(); err != nil {
			return err
		}
	}
	defer resp.Body.Close()
	lastStatus = resp.StatusCode
	if dumpHeaders {
		fmt.Printf("HTTP/1.1 %s\r\n", resp.Status)
		keys := make([]string, 0, len(resp.Header))
		for k := range resp.Header {
			keys = append(keys, k)
		}
		sort.Strings(keys)
		for _, k := range keys {
			for _, v := range resp.Header[k] {
				fmt.Printf("%s: %s\r\n", strings.ToLower(k), v)
			}
		}
		fmt.Print("\r\n")
	}
	b, _ := io.ReadAll(resp.Body)
	if outFile != "/dev/null" {
		os.Stdout.Write(b)
	}
	if wfmt != "" {
		fmt.Print(strings.ReplaceAll(wfmt, "%{http_code}", fmt.Sprint(resp.StatusCode)))
	}
	return nil
}

// deviceKey: cihaz anahtarı (ilk kullanımda üretilir). DEVICE_KEY ile başka bir anahtar (saldırgan cihazı) seçilebilir.
func deviceKey() (*ecdsa.PrivateKey, error) {
	path := env("DEVICE_KEY", state+"/device.key")
	if b, err := os.ReadFile(path); err == nil {
		blk, _ := pem.Decode(b)
		if blk == nil {
			return nil, errors.New("anahtar dosyası bozuk")
		}
		return x509.ParseECPrivateKey(blk.Bytes)
	}
	k, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		return nil, err
	}
	der, _ := x509.MarshalECPrivateKey(k)
	return k, os.WriteFile(path, pem.EncodeToMemory(&pem.Block{Type: "EC PRIVATE KEY", Bytes: der}), 0600)
}

func jwk(k *ecdsa.PrivateKey) map[string]string {
	x, y := make([]byte, 32), make([]byte, 32)
	k.PublicKey.X.FillBytes(x)
	k.PublicKey.Y.FillBytes(y)
	return map[string]string{"kty": "EC", "crv": "P-256", "x": b64.EncodeToString(x), "y": b64.EncodeToString(y)}
}

func thumbprint(k *ecdsa.PrivateKey) string {
	j := jwk(k)
	h := sha256.Sum256([]byte(`{"crv":"P-256","kty":"EC","x":"` + j["x"] + `","y":"` + j["y"] + `"}`))
	return b64.EncodeToString(h[:])
}

func dpopProof(k *ecdsa.PrivateKey, method, htu, token string) string {
	ath := sha256.Sum256([]byte(token))
	return signES256(k, map[string]any{"typ": "dpop+jwt", "alg": "ES256", "jwk": jwk(k)},
		map[string]any{"jti": random(16), "htm": method, "htu": htu, "iat": time.Now().Unix(), "ath": b64.EncodeToString(ath[:])})
}

// attestation: lab'de Play Integrity / App Attest yerine; sağlayıcının anahtarıyla imzalı, cihaz anahtarına bağlı
func attestation(device *ecdsa.PrivateKey) string {
	b, err := os.ReadFile(env("ATTEST_KEY", "/attest/attest.key"))
	if err != nil {
		fail("attestation anahtarı: " + err.Error())
	}
	blk, _ := pem.Decode(b)
	var provider *ecdsa.PrivateKey
	if k, err := x509.ParsePKCS8PrivateKey(blk.Bytes); err == nil {
		provider, _ = k.(*ecdsa.PrivateKey)
	} else if provider, err = x509.ParseECPrivateKey(blk.Bytes); err != nil {
		fail("attestation anahtarı: " + err.Error())
	}
	now := time.Now().Unix()
	return signES256(provider, map[string]any{"typ": "JWT", "alg": "ES256"}, map[string]any{
		"iss": "lab-attestation", "app_id": env("APP_ID", "tr.com.example.bank"), "app_version": env("APP_VERSION", "3.2.0"),
		"integrity": env("INTEGRITY", "MEETS_DEVICE_INTEGRITY"), "jkt": thumbprint(device), "iat": now, "exp": now + 300})
}

func signES256(k *ecdsa.PrivateKey, header, claims map[string]any) string {
	h, _ := json.Marshal(header)
	c, _ := json.Marshal(claims)
	input := b64.EncodeToString(h) + "." + b64.EncodeToString(c)
	d := sha256.Sum256([]byte(input))
	r, s, err := ecdsa.Sign(rand.Reader, k, d[:])
	if err != nil {
		fail(err.Error())
	}
	sig := make([]byte, 64)
	r.FillBytes(sig[:32])
	s.FillBytes(sig[32:])
	return input + "." + b64.EncodeToString(sig)
}

// --- yük üretici ---

func loop() {
	ready := false
	for i := 0; ; i++ {
		if !ready {
			if err := login("2"); err != nil {
				fmt.Fprintln(os.Stderr, "giriş:", err)
				time.Sleep(15 * time.Second)
				continue
			}
			err := call([]string{"-o", "/dev/null", "-X", "POST", "-d", `{"name":"loadgen"}`, "/mobile/v1/devices"})
			if err != nil || (lastStatus != http.StatusCreated && lastStatus != http.StatusOK) {
				fmt.Fprintln(os.Stderr, "cihaz kaydı:", err, lastStatus)
				time.Sleep(15 * time.Second)
				continue
			}
			ready = true
		}
		err := call([]string{"-o", "/dev/null", "/mobile/v1/accounts"})
		if err != nil || lastStatus == http.StatusUnauthorized || lastStatus == http.StatusForbidden {
			fmt.Fprintln(os.Stderr, "istek:", err, lastStatus, "- yeniden giriş ve cihaz kaydı")
			ready = false
		}
		time.Sleep(time.Second)
	}
}

// --- yardımcılar ---

// totp: RFC 6238 (HMAC-SHA1, 30 sn, 6 hane); Keycloak'ın OTP gizi düz metin, anahtar onun baytları
func totp(secret string, t time.Time) string {
	var c [8]byte
	binary.BigEndian.PutUint64(c[:], uint64(t.Unix()/30))
	m := hmac.New(sha1.New, []byte(secret))
	m.Write(c[:])
	h := m.Sum(nil)
	o := h[len(h)-1] & 0x0f
	return fmt.Sprintf("%06d", (binary.BigEndian.Uint32(h[o:o+4])&0x7fffffff)%1000000)
}

func random(n int) string {
	b := make([]byte, n)
	rand.Read(b)
	return b64.EncodeToString(b)
}

func save(name string, v any) error {
	os.MkdirAll(state, 0700)
	b, _ := json.Marshal(v)
	return os.WriteFile(state+"/"+name, b, 0600)
}

func load(name string, v any) error {
	b, err := os.ReadFile(state + "/" + name)
	if err != nil {
		return err
	}
	return json.Unmarshal(b, v)
}

func fail(msg string) {
	fmt.Fprintln(os.Stderr, "mobile-sim:", msg)
	os.Exit(1)
}

func env(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}
