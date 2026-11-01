// account-api: hesap bilgilerini PostgreSQL'den (mgmt) okuyan internal servis. cluster-a'da çalışır.
//
//	/healthz        -> kendi sağlık kontrolü (veritabanına bağlı değil)
//	/readyz         -> veritabanı erişilebilir mi
//	GET  /accounts                 -> kullanıcının görebildiği hesaplar (en fazla 20)
//	GET  /accounts/{id}            -> tek hesap (sahibi değilse 404)
//	POST /accounts/{id}/transfers  -> örnek yazma ucu: transfers:write, web/mobilde son 5 dk içinde seviye 2, şubede gişe/operasyon (09b)
//	GET  /products                 -> ürün kataloğu (partner yetkisi örneği)
//
// Nesne seviyesinde yetki (BOLA, 09b): müşteri yalnızca kendi hesaplarını (owner_sub = sub), partner yalnızca kendisine
// bağlı hesapları (partner_id) görür; personel tüm hesapları görür ve her erişimi loglanır. Mesh hangi hesabın kime
// ait olduğunu bilemez; bu karar uygulamada.
//
// Veritabanı bağlantısı libpq ortam değişkenlerinden gelir (PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD).
// Bağlantı mesh üzerinden gider: account-api -> waypoint -> istio-egressgateway -> mgmt ingress gw -> postgres.
// Uygulamanın kendi TLS'i yok (PGSSLMODE=disable); taşıma şifrelemesi mesh mTLS'inde.
package main

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"log"
	"net/http"
	"os"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

var version = "dev" // build sırasında -ldflags ile verilir

type account struct {
	ID       int64  `json:"id"`
	IBAN     string `json:"iban"` // maskeli
	Owner    string `json:"owner"`
	Currency string `json:"currency"`
	Balance  string `json:"balance"`
}

func main() {
	ctx := context.Background()
	cfg, err := pgxpool.ParseConfig("") // boş: libpq ortam değişkenleri
	if err != nil {
		log.Fatalf("veritabanı yapılandırması: %v", err)
	}
	cfg.MaxConns = 4
	cfg.MaxConnIdleTime = time.Minute
	pool, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		log.Fatalf("veritabanı havuzu: %v", err)
	}
	defer pool.Close()

	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
	})
	mux.HandleFunc("GET /readyz", func(w http.ResponseWriter, r *http.Request) {
		ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
		defer cancel()
		if err := pool.Ping(ctx); err != nil {
			log.Printf("readyz: %v", err)
			writeJSON(w, http.StatusServiceUnavailable, map[string]string{"status": "db_unavailable"})
			return
		}
		writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
	})
	mux.HandleFunc("GET /accounts", func(w http.ResponseWriter, r *http.Request) {
		u := userFrom(r)
		cond, arg, ok := ownership(u)
		if !ok {
			writeJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
			return
		}
		rows, err := pool.Query(r.Context(),
			`SELECT id, iban, owner, currency, balance::text FROM accounts.accounts WHERE `+cond+` ORDER BY id LIMIT 20`, arg...)
		if err != nil {
			dbError(w, r, err)
			return
		}
		list, err := pgx.CollectRows(rows, scanAccount)
		if err != nil {
			dbError(w, r, err)
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{"accounts": list, "source": "postgresql", "service": "account-api " + version})
	})
	mux.HandleFunc("GET /accounts/{id}", func(w http.ResponseWriter, r *http.Request) {
		acc, status := findOwned(r, pool)
		if status != http.StatusOK {
			writeJSON(w, status, map[string]string{"error": http.StatusText(status)})
			return
		}
		writeJSON(w, http.StatusOK, acc)
	})
	// Örnek yazma ucu (09b): gerçek işlem yapmaz (veritabanı kullanıcısı yalnızca okuyabilir); kararı ve kaydı gösterir.
	// Kurallar waypoint'te de var (scope, acr, kanal); burada tekrar (derinlemesine savunma) + sahiplik.
	mux.HandleFunc("POST /accounts/{id}/transfers", func(w http.ResponseWriter, r *http.Request) {
		u := userFrom(r)
		if !u.hasScope("transfers:write") {
			writeJSON(w, http.StatusForbidden, map[string]string{"error": "insufficient_scope"})
			return
		}
		switch u.Channel {
		case "web", "mobile":
			if !u.levelFresh("2", 5*time.Minute) { // RFC 9470: istemci step-up yapmalı
				w.Header().Set("WWW-Authenticate", `Bearer error="insufficient_user_authentication", acr_values="2"`)
				writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "insufficient_user_authentication", "acr_values": "2"})
				return
			}
		case "branch":
			if !slices.Contains(u.Roles, "teller") && !slices.Contains(u.Roles, "operations") {
				writeJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
				return
			}
		default: // partner ve diğerleri: yazma yok
			writeJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
			return
		}
		var req struct {
			ToIBAN string `json:"to_iban"`
			Amount string `json:"amount"`
		}
		if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 4<<10)).Decode(&req); err != nil || req.ToIBAN == "" || req.Amount == "" {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid_request"})
			return
		}
		acc, status := findOwned(r, pool)
		if status != http.StatusOK {
			writeJSON(w, status, map[string]string{"error": http.StatusText(status)})
			return
		}
		ref := "TRX-" + strconv.FormatInt(time.Now().UnixNano(), 36)
		log.Printf("TRANSFER kabul ref=%s hesap=%d alici=%s tutar=%s sub=%q kanal=%q loa=%s", ref, acc.ID, maskIBAN(req.ToIBAN), req.Amount, u.Sub, u.Channel, u.LoaMap)
		writeJSON(w, http.StatusAccepted, map[string]string{"status": "accepted", "reference": ref, "note": "lab: işlem yapılmaz, yalnızca kaydedilir"})
	})
	// Ürün kataloğu (09b): partner yetkisi örneği (products:read). Statik, veritabanı yok.
	mux.HandleFunc("GET /products", func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, http.StatusOK, map[string]any{"products": []map[string]string{
			{"code": "VDS-TRY", "name": "Vadesiz TL hesabı"},
			{"code": "VDL-USD", "name": "Vadeli döviz hesabı"},
			{"code": "KRD-IHT", "name": "İhtiyaç kredisi"},
		}})
	})

	srv := &http.Server{
		Addr:              ":" + env("PORT", "8080"),
		Handler:           logRequests(mux),
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       10 * time.Second,
		WriteTimeout:      15 * time.Second,
		MaxHeaderBytes:    32 << 10,
	}
	log.Printf("account-api %s dinliyor: %s (db %s/%s)", version, srv.Addr, os.Getenv("PGHOST"), os.Getenv("PGDATABASE"))
	log.Fatal(srv.ListenAndServe())
}

func scanAccount(row pgx.CollectableRow) (account, error) {
	var a account
	err := row.Scan(&a.ID, &a.IBAN, &a.Owner, &a.Currency, &a.Balance)
	a.IBAN = maskIBAN(a.IBAN)
	return a, err
}

// IBAN'ın yalnızca ülke kodu ve son 4 hanesi görünür
func maskIBAN(s string) string {
	if len(s) <= 6 {
		return "****"
	}
	return s[:2] + "**************" + s[len(s)-4:]
}

// Veritabanı hatasının ayrıntısı loglanır, istemciye dönmez
func dbError(w http.ResponseWriter, r *http.Request, err error) {
	log.Printf("db hatası: %s %s: %v", r.Method, r.URL.Path, err)
	writeJSON(w, http.StatusServiceUnavailable, map[string]string{"error": "db_unavailable"})
}

// Her istekte kim (iç JWT: sub, roller, kanal), hangi istek kimliğiyle loglanır (denetim izi).
// JWT'nin imzası mesh'te (RequestAuthentication, waypoint) doğrulandı; burada yalnızca okunur.
func logRequests(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		next.ServeHTTP(w, r)
		if r.URL.Path != "/healthz" && r.URL.Path != "/readyz" {
			u := userFrom(r)
			log.Printf("%s %s sub=%q roles=%v channel=%q partner=%q branch=%q sid=%q request_id=%q %s", r.Method, r.URL.Path,
				u.Sub, u.Roles, u.Channel, u.PartnerID, u.BranchID, u.Sid, r.Header.Get("x-request-id"), time.Since(start).Round(time.Millisecond))
		}
	})
}

type user struct {
	Sub       string   `json:"sub"`
	Scope     string   `json:"scope"`
	// loa_map: IdP oturumunda ulaşılan doğrulama seviyeleri ve zamanları ({"1":<unix>,"2":<unix>}). Keycloak token
	// exchange acr'yi taşımıyor (hep "1"); seviye kontrolü bu IdP imzalı claim'le yapılır (09b bulgusu).
	LoaMap    string   `json:"loa_map"`
	Roles     []string `json:"roles"`
	Channel   string   `json:"channel"`
	PartnerID string   `json:"partner_id"`
	BranchID  string   `json:"branch_id"` // personelin şubesi (IdP'deki grup attribute'u; 09a)
	Sid       string   `json:"sid"`       // IdP oturumu: aynı oturumun istekleri ilişkilendirilebilir
}

func (u user) hasScope(s string) bool { return slices.Contains(strings.Fields(u.Scope), s) }

// levelFresh: kullanıcı bu oturumda en az bu seviyeyle, en fazla maxAge önce doğrulandı mı (step-up tazeliği)
func (u user) levelFresh(level string, maxAge time.Duration) bool {
	var m map[string]int64
	if json.Unmarshal([]byte(u.LoaMap), &m) != nil {
		return false
	}
	t, ok := m[level]
	return ok && time.Since(time.Unix(t, 0)) <= maxAge
}

// ownership: kullanıcının görebileceği hesaplar için SQL koşulu (BOLA). ok=false: hiçbir hesap.
func ownership(u user) (string, []any, bool) {
	switch {
	case !u.hasScope("accounts:read") && !u.hasScope("transfers:write"):
		return "", nil, false
	case u.Channel == "partner" && u.PartnerID != "":
		return "partner_id = $1", []any{u.PartnerID}, true
	case (u.Channel == "web" || u.Channel == "mobile") && u.Sub != "":
		return "owner_sub = $1", []any{u.Sub}, true
	case u.Channel == "branch" && (slices.Contains(u.Roles, "teller") || slices.Contains(u.Roles, "operations")):
		log.Printf("PERSONEL ERİŞİMİ sub=%q şube=%q roller=%v", u.Sub, u.BranchID, u.Roles)
		return "true", nil, true
	}
	return "", nil, false
}

// findOwned: {id} hesabını kullanıcının yetkisiyle arar. Sahibi değilse 404 (hesabın varlığı sızdırılmaz).
func findOwned(r *http.Request, pool *pgxpool.Pool) (account, int) {
	id, err := strconv.ParseInt(r.PathValue("id"), 10, 64)
	if err != nil || id <= 0 {
		return account{}, http.StatusBadRequest
	}
	cond, arg, ok := ownership(userFrom(r))
	if !ok {
		return account{}, http.StatusForbidden
	}
	rows, _ := pool.Query(r.Context(),
		`SELECT id, iban, owner, currency, balance::text FROM accounts.accounts WHERE id = $1 AND `+shift(cond)+``,
		append([]any{id}, arg...)...)
	acc, err := pgx.CollectExactlyOneRow(rows, scanAccount)
	switch {
	case errors.Is(err, pgx.ErrNoRows):
		return account{}, http.StatusNotFound
	case err != nil:
		log.Printf("db hatası: %s %s: %v", r.Method, r.URL.Path, err)
		return account{}, http.StatusServiceUnavailable
	}
	return acc, http.StatusOK
}

// shift: koşuldaki $1'i $2 yapar (önde id parametresi var)
func shift(cond string) string { return strings.ReplaceAll(cond, "$1", "$2") }

// userFrom: x-user-jwt payload'unu okur (doğrulama mesh'te yapıldı)
func userFrom(r *http.Request) user {
	var u user
	parts := strings.Split(r.Header.Get("x-user-jwt"), ".")
	if len(parts) == 3 {
		if b, err := base64.RawURLEncoding.DecodeString(parts[1]); err == nil {
			json.Unmarshal(b, &u)
		}
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
