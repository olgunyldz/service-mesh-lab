// account-api: hesap bilgilerini PostgreSQL'den (mgmt) okuyan internal servis. cluster-a'da çalışır.
//
//	/healthz        -> kendi sağlık kontrolü (veritabanına bağlı değil)
//	/readyz         -> veritabanı erişilebilir mi
//	/accounts       -> hesap listesi (en fazla 20)
//	/accounts/{id}  -> tek hesap
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
		rows, err := pool.Query(r.Context(),
			`SELECT id, iban, owner, currency, balance::text FROM accounts.accounts ORDER BY id LIMIT 20`)
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
		id, err := strconv.ParseInt(r.PathValue("id"), 10, 64)
		if err != nil || id <= 0 {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid_id"})
			return
		}
		rows, _ := pool.Query(r.Context(),
			`SELECT id, iban, owner, currency, balance::text FROM accounts.accounts WHERE id = $1`, id)
		acc, err := pgx.CollectExactlyOneRow(rows, scanAccount)
		if errors.Is(err, pgx.ErrNoRows) {
			writeJSON(w, http.StatusNotFound, map[string]string{"error": "not_found"})
			return
		}
		if err != nil {
			dbError(w, r, err)
			return
		}
		writeJSON(w, http.StatusOK, acc)
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
	Roles     []string `json:"roles"`
	Channel   string   `json:"channel"`
	PartnerID string   `json:"partner_id"`
	BranchID  string   `json:"branch_id"` // personelin şubesi (IdP'deki grup attribute'u; 09a)
	Sid       string   `json:"sid"`       // IdP oturumu: aynı oturumun istekleri ilişkilendirilebilir
}

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
