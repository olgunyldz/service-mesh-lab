// device-registry: mobil cihaz kayıtları (09c · mobile-binding). mgmt'te, kimlik tarafında (ns iam) çalışır.
//
// Bir cihaz = kullanıcı (IdP sub) + cihazın public key'i (JWK, RFC 7638 thumbprint = jkt). Private key cihazdan çıkmaz;
// cihaz her istekte DPoP kanıtını bu anahtarla imzalar. DMZ (auth-service) her istekte "bu anahtar bu kullanıcıya
// kayıtlı ve etkin mi?" diye sorar.
//
//	GET    /v1/devices/lookup?sub=&jkt=  -> 200 {device_id} | 404        (DMZ, her mobil istekte; önbellekli)
//	POST   /v1/devices                   -> 201 {device_id, jkt}         (mobile-bff: kayıt)
//	GET    /v1/devices?sub=              -> kullanıcının cihazları        (mobile-bff)
//	DELETE /v1/devices/{id}?sub=         -> 204                           (mobile-bff: kayıt silme, ör. kayıp telefon)
//
// Çağıranlar mesh kimliğiyle sınırlı (mgmt girişindeki AuthorizationPolicy); sub, çağıranın doğruladığı iç JWT'den gelir.
package main

import (
	"context"
	"encoding/json"
	"errors"
	"log"
	"net/http"
	"os"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

var version = "dev" // build sırasında -ldflags ile verilir

const maxDevicesPerUser = 3

const schema = `
CREATE TABLE IF NOT EXISTS devices (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  sub         text NOT NULL,
  jkt         text NOT NULL UNIQUE,
  jwk         jsonb NOT NULL,
  app_id      text NOT NULL,
  app_version text NOT NULL,
  name        text NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now(),
  revoked_at  timestamptz
);
CREATE INDEX IF NOT EXISTS devices_sub ON devices (sub) WHERE revoked_at IS NULL;`

type device struct {
	ID         string    `json:"device_id"`
	JKT        string    `json:"jkt"`
	AppID      string    `json:"app_id"`
	AppVersion string    `json:"app_version"`
	Name       string    `json:"name"`
	CreatedAt  time.Time `json:"created_at"`
}

func main() {
	ctx := context.Background()
	cfg, err := pgxpool.ParseConfig("") // libpq ortam değişkenleri
	if err != nil {
		log.Fatalf("veritabanı yapılandırması: %v", err)
	}
	cfg.MaxConns = 4
	pool, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		log.Fatalf("veritabanı havuzu: %v", err)
	}
	defer pool.Close()
	for i := 0; ; i++ { // veritabanı geç açılabilir
		if _, err = pool.Exec(ctx, schema); err == nil {
			break
		}
		if i == 30 {
			log.Fatalf("şema: %v", err)
		}
		time.Sleep(2 * time.Second)
	}

	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, _ *http.Request) { writeJSON(w, http.StatusOK, map[string]string{"status": "ok"}) })

	mux.HandleFunc("GET /v1/devices/lookup", func(w http.ResponseWriter, r *http.Request) {
		sub, jkt := r.URL.Query().Get("sub"), r.URL.Query().Get("jkt")
		if sub == "" || jkt == "" {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "sub_and_jkt_required"})
			return
		}
		var id string
		err := pool.QueryRow(r.Context(), `SELECT id::text FROM devices WHERE sub = $1 AND jkt = $2 AND revoked_at IS NULL`, sub, jkt).Scan(&id)
		switch {
		case errors.Is(err, pgx.ErrNoRows):
			writeJSON(w, http.StatusNotFound, map[string]string{"error": "device_not_registered"})
		case err != nil:
			dbError(w, err)
		default:
			writeJSON(w, http.StatusOK, map[string]string{"device_id": id})
		}
	})

	mux.HandleFunc("POST /v1/devices", func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			Sub        string          `json:"sub"`
			JKT        string          `json:"jkt"`
			JWK        json.RawMessage `json:"jwk"`
			AppID      string          `json:"app_id"`
			AppVersion string          `json:"app_version"`
			Name       string          `json:"name"`
		}
		if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 8<<10)).Decode(&req); err != nil ||
			req.Sub == "" || req.JKT == "" || len(req.JWK) == 0 || req.AppID == "" {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid_request"})
			return
		}
		if req.Name == "" {
			req.Name = "telefon"
		}
		var n int
		if err := pool.QueryRow(r.Context(), `SELECT count(*) FROM devices WHERE sub = $1 AND revoked_at IS NULL`, req.Sub).Scan(&n); err != nil {
			dbError(w, err)
			return
		}
		if n >= maxDevicesPerUser {
			writeJSON(w, http.StatusConflict, map[string]string{"error": "too_many_devices"})
			return
		}
		var id string
		// Aynı anahtar başka bir kullanıcıya kayıtlı olamaz (jkt UNIQUE); aynı kullanıcı yeniden kaydederse güncellenir
		err := pool.QueryRow(r.Context(), `
			INSERT INTO devices (sub, jkt, jwk, app_id, app_version, name) VALUES ($1, $2, $3, $4, $5, $6)
			ON CONFLICT (jkt) DO UPDATE SET app_version = EXCLUDED.app_version, revoked_at = NULL
			  WHERE devices.sub = EXCLUDED.sub
			RETURNING id::text`, req.Sub, req.JKT, req.JWK, req.AppID, req.AppVersion, req.Name).Scan(&id)
		if errors.Is(err, pgx.ErrNoRows) {
			writeJSON(w, http.StatusConflict, map[string]string{"error": "key_registered_to_another_user"})
			return
		}
		if err != nil {
			dbError(w, err)
			return
		}
		log.Printf("CİHAZ KAYDI device_id=%s sub=%s app=%s/%s", id, req.Sub, req.AppID, req.AppVersion)
		writeJSON(w, http.StatusCreated, map[string]string{"device_id": id, "jkt": req.JKT})
	})

	mux.HandleFunc("GET /v1/devices", func(w http.ResponseWriter, r *http.Request) {
		sub := r.URL.Query().Get("sub")
		if sub == "" {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "sub_required"})
			return
		}
		rows, _ := pool.Query(r.Context(), `SELECT id::text, jkt, app_id, app_version, name, created_at FROM devices
			WHERE sub = $1 AND revoked_at IS NULL ORDER BY created_at`, sub)
		list, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (device, error) {
			var d device
			return d, row.Scan(&d.ID, &d.JKT, &d.AppID, &d.AppVersion, &d.Name, &d.CreatedAt)
		})
		if err != nil {
			dbError(w, err)
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{"devices": list})
	})

	mux.HandleFunc("DELETE /v1/devices/{id}", func(w http.ResponseWriter, r *http.Request) {
		sub := r.URL.Query().Get("sub")
		tag, err := pool.Exec(r.Context(), `UPDATE devices SET revoked_at = now() WHERE id::text = $1 AND sub = $2 AND revoked_at IS NULL`,
			r.PathValue("id"), sub)
		if err != nil {
			dbError(w, err)
			return
		}
		if tag.RowsAffected() == 0 {
			writeJSON(w, http.StatusNotFound, map[string]string{"error": "not_found"})
			return
		}
		log.Printf("CİHAZ SİLİNDİ device_id=%s sub=%s", r.PathValue("id"), sub)
		w.WriteHeader(http.StatusNoContent)
	})

	srv := &http.Server{
		Addr:              ":" + env("PORT", "8080"),
		Handler:           mux,
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       10 * time.Second,
		WriteTimeout:      10 * time.Second,
		MaxHeaderBytes:    16 << 10,
	}
	log.Printf("device-registry %s dinliyor: %s", version, srv.Addr)
	log.Fatal(srv.ListenAndServe())
}

func dbError(w http.ResponseWriter, err error) {
	log.Printf("db hatası: %v", err)
	writeJSON(w, http.StatusServiceUnavailable, map[string]string{"error": "db_unavailable"})
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
