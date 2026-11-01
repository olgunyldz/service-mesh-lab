// web-bff: web kanalının arka ucu (Backend for Frontend). DMZ'de çalışır.
//
//	/healthz          -> kendi sağlık kontrolü
//	/bff/v1/dashboard -> api-a'nın birkaç ucunu paralel çağırıp web'e uygun tek yanıt üretir
//	diğer her yol     -> api-a'ya iletilir (ters proxy)
//
// api-a'ya giden istekler mesh üzerinden gider: web-bff -> waypoint -> dmz-egressgateway -> cluster-a.
// Yalnızca standart kütüphane kullanır (bağımlılık yok, distroless static image).
package main

import (
	"context"
	"encoding/json"
	"io"
	"log"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"sync"
	"time"
)

var version = "dev" // build sırasında -ldflags ile verilir

func main() {
	upstream, err := url.Parse(env("API_URL", "http://api-a"))
	if err != nil {
		log.Fatalf("API_URL geçersiz: %v", err)
	}
	client := &http.Client{Timeout: 5 * time.Second}

	proxy := httputil.NewSingleHostReverseProxy(upstream)
	// Hata ayrıntısı (iç adres, bağlantı hatası) istemciye dönmesin
	proxy.ErrorHandler = func(w http.ResponseWriter, r *http.Request, err error) {
		log.Printf("upstream hatası: %s %s: %v", r.Method, r.URL.Path, err)
		writeJSON(w, http.StatusBadGateway, map[string]string{"error": "upstream_unavailable"})
	}

	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
	})
	mux.HandleFunc("GET /bff/v1/dashboard", dashboard(client, upstream))
	mux.Handle("/", proxy)

	srv := &http.Server{
		Addr:              ":" + env("PORT", "8080"),
		Handler:           securityHeaders(mux),
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       10 * time.Second,
		WriteTimeout:      15 * time.Second,
		MaxHeaderBytes:    32 << 10,
	}
	log.Printf("web-bff %s dinliyor: %s (upstream %s)", version, srv.Addr, upstream)
	log.Fatal(srv.ListenAndServe())
}

// dashboard: api-a'nın "/" ve "/version" uçlarını paralel çağırır, web'in ihtiyaç duyduğu alanları seçer.
func dashboard(client *http.Client, upstream *url.URL) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		ctx, cancel := context.WithTimeout(r.Context(), 4*time.Second)
		defer cancel()

		paths := []string{"/", "/version"}
		results := make([]map[string]any, len(paths))
		errs := make([]error, len(paths))
		var wg sync.WaitGroup
		for i, p := range paths {
			wg.Add(1)
			go func() {
				defer wg.Done()
				results[i], errs[i] = getJSON(ctx, client, upstream.JoinPath(p).String(), r.Header)
			}()
		}
		wg.Wait()
		for _, err := range errs {
			if err != nil {
				log.Printf("dashboard: %v", err)
				writeJSON(w, http.StatusBadGateway, map[string]string{"error": "upstream_unavailable"})
				return
			}
		}
		writeJSON(w, http.StatusOK, map[string]any{
			"channel": "web",
			"bff":     version,
			"service": results[0]["message"],
			"version": results[1]["version"],
			"commit":  results[1]["commit"],
		})
	}
}

// Kimlik (iç JWT), izlenebilirlik ve kanal header'ları upstream'e taşınır. Mesh header'ları kendiliğinden
// kopyalamaz; x-user-jwt'yi iletmek uygulamanın işi (ters proxy yolları zaten tüm header'ları iletiyor).
var forwardHeaders = []string{"x-user-jwt", "x-request-id", "x-channel", "traceparent", "tracestate"}

func getJSON(ctx context.Context, client *http.Client, u string, in http.Header) (map[string]any, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, u, nil)
	if err != nil {
		return nil, err
	}
	for _, h := range forwardHeaders {
		if v := in.Get(h); v != "" {
			req.Header.Set(h, v)
		}
	}
	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		io.Copy(io.Discard, resp.Body)
		return nil, &upstreamError{u, resp.StatusCode}
	}
	var out map[string]any
	return out, json.NewDecoder(io.LimitReader(resp.Body, 1<<20)).Decode(&out)
}

type upstreamError struct {
	url    string
	status int
}

func (e *upstreamError) Error() string { return e.url + ": HTTP " + http.StatusText(e.status) }

// Web (tarayıcı) kanalına özel güvenlik header'ları
func securityHeaders(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		h := w.Header()
		h.Set("X-Content-Type-Options", "nosniff")
		h.Set("X-Frame-Options", "DENY")
		h.Set("Referrer-Policy", "no-referrer")
		h.Set("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
		h.Set("Cache-Control", "no-store")
		next.ServeHTTP(w, r)
	})
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
