// branch-bff: şube kanalının arka ucu (Backend for Frontend). Internal'da (cluster-a, ns channel-bff) çalışır (09e).
//
//	/healthz                       -> kendi sağlık kontrolü (mesai saatinden bağımsız)
//	/accounts*, /products          -> account-api (hesaplar personelin şubesiyle sınırlı; limit üstü transfer onaya düşer)
//	/approvals*                    -> account-api (dört göz onayı: yalnızca yetkili, aynı şube, talep edenden farklı kişi)
//	diğer her yol                  -> api-a
//
// Mesai saati: BRANCH_HOURS (SS:DD-SS:DD, Türkiye saati) dışındaki her istek 403 outside_business_hours. Kanal kuralı
// olduğu için burada: domain servisleri şube kanalını yalnızca branch-bff'in kimliğinden kabul eder (waypoint), yani
// bu kontrol atlanamaz.
//
// Önündeki zincir: şube terminali -> branch-fw -> branch-gateway (cihaz sertifikası, ext_authz: personel token'ı,
// cihaz ↔ şube, iç JWT) -> DMZ egress -> int-ingressgw -> branch-bff.
package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"time"
)

var version = "dev" // build sırasında -ldflags ile verilir

// Türkiye saati sabit UTC+3 (yaz saati yok); distroless image'da tz veritabanı gerekmez
var trTime = time.FixedZone("TRT", 3*60*60)

func main() {
	api := mustURL(env("API_URL", "http://api-a.api-a.svc.cluster.local"))
	accounts := mustURL(env("ACCOUNTS_URL", "http://account-api.account-api.svc.cluster.local:8080"))
	hours := env("BRANCH_HOURS", "09:00-17:30")
	open, closeAt, err := parseHours(hours)
	if err != nil {
		log.Fatalf("BRANCH_HOURS geçersiz %q: %v", hours, err)
	}

	accountsProxy := reverseProxy(accounts)
	mux := http.NewServeMux()
	mux.Handle("/accounts", accountsProxy)
	mux.Handle("/accounts/", accountsProxy)
	mux.Handle("/products", accountsProxy)
	mux.Handle("/approvals", accountsProxy)
	mux.Handle("/approvals/", accountsProxy)
	mux.Handle("/", reverseProxy(api))

	root := http.NewServeMux()
	root.HandleFunc("GET /healthz", func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
	})
	root.Handle("/", businessHours(open, closeAt, hours, mux))

	srv := &http.Server{
		Addr:              ":" + env("PORT", "8080"),
		Handler:           root,
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       10 * time.Second,
		WriteTimeout:      15 * time.Second,
		MaxHeaderBytes:    32 << 10,
	}
	log.Printf("branch-bff %s dinliyor: %s (api %s, hesaplar %s, mesai %s)", version, srv.Addr, api, accounts, hours)
	log.Fatal(srv.ListenAndServe())
}

// businessHours: mesai dışında istek reddedilir (gün içindeki dakika, [open, close) aralığı)
func businessHours(open, closeAt int, hours string, next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		now := time.Now().In(trTime)
		m := now.Hour()*60 + now.Minute()
		if m < open || m >= closeAt {
			log.Printf("MESAİ DIŞI %s %s saat=%s request_id=%q", r.Method, r.URL.Path, now.Format("15:04"), r.Header.Get("x-request-id"))
			writeJSON(w, http.StatusForbidden, map[string]string{"error": "outside_business_hours", "hours": hours})
			return
		}
		next.ServeHTTP(w, r)
	})
}

// parseHours: "09:00-17:30" -> (540, 1050); bitiş 24:00 olabilir
func parseHours(s string) (int, int, error) {
	var h1, m1, h2, m2 int
	if _, err := fmt.Sscanf(s, "%d:%d-%d:%d", &h1, &m1, &h2, &m2); err != nil {
		return 0, 0, err
	}
	open, closeAt := h1*60+m1, h2*60+m2
	if h1 > 23 || m1 > 59 || m2 > 59 || closeAt > 24*60 || open >= closeAt {
		return 0, 0, fmt.Errorf("aralık geçersiz")
	}
	return open, closeAt, nil
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
