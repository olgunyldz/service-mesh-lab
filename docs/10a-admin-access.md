# 10a · Yönetim arayüzleri: Keycloak yönetim konsolu, Loki panoları

| | |
|---|---|
| **Branch** | `admin-access` (açıldığı yer: `logging`) |
| **Durum** | ✅ Tamamlandı, sıfırdan kurulumla doğrulandı (250/250 test) |

## Amaç

Kullanıcının iki isteği:
- **Keycloak yönetim konsolu komut çalıştırmadan açılsın.** 10'da yalnızca `kubectl port-forward` ile açılıyordu.
- **Loki için panolar.** Loglar yalnızca Explore'da sorgulanabiliyordu.

## Adım sonundaki durum

| Konu | Durum |
|------|-------|
| Keycloak yönetim konsolu | **http://localhost:8081/admin** (kullanıcı `admin`, parola `certs/data/keycloak-admin.pw`). Port host'ta yalnızca `127.0.0.1`'e bağlı: bu makine dışından açılmaz. İnternet ve DMZ tarafında `/admin` ve master realm kapalı kalır |
| Yol | tarayıcı → 127.0.0.1:8081 (kind port eşlemesi) → node :30808 → mgmt istio-ingressgateway'in yönetim dinleyicisi (:8081) → mesh (ingress gateway kimliği) → keycloak:8080 |
| Bu kapının izinleri | Yalnızca `/admin*`, `/realms/master*`, `/resources/*`. Uygulama realm'leri (customers, partners, staff) 403. Keycloak'ın kendi kuralı değişmedi (L4'te yalnızca ingress gateway kimliği) |
| Keycloak ayarı | `KC_HOSTNAME_ADMIN=http://localhost:8081`, master realm `frontendUrl=http://localhost:8081` (07b). Uygulama realm'leri `sso.apps.example.local` adını kullanmaya devam eder |
| Loki panoları | Grafana'da (http://localhost:3001), `infra/logging/dashboards/` (üreteç: `generate.py`): Main Org'da **Loglar - Genel bakış**, her ekip organizasyonunda kendi panosu. Yönetici tüm organizasyonlara Admin olarak eklenir |

### Panolar

| Pano | Organizasyon | İçerik |
|------|--------------|--------|
| Loglar - Genel bakış | Main Org (yönetici) | Kategori başına satır sayısı ve zaman serisi, zone'a göre hacim; WAF engellemesi, auth-service reddi, dört göz ihlali, secret değişikliği (audit); cluster'a göre 4xx / 5xx; **`request_id` kutusuyla tüm kategorilerde iz**; son hatalar |
| Network - Access log'lar | Network | Yanıt kodu, kanal, süre p95, Envoy yanıt bayrakları, en çok hata dönen hedefler, edge container'ları, hatalı istekler |
| Security - Güvenlik olayları | Security | WAF, auth-service reddi (sebebe göre), Keycloak giriş hatası, personel erişimi; audit: işlem / kaynak / kullanıcı, secret erişimi; güvenlik olayları akışı |
| Apps - Uygulama logları | Apps | Servise göre hacim, hata satırları, transfer kabul / onay bekliyor / onaylandı, auth-service izinleri, transfer kayıtları |
| DB - PostgreSQL ve Valkey | DB | Başarısız giriş, yetki reddi, ERROR / FATAL, Valkey ACL reddi, hatalar |
| Infra - Platform uyarı ve hataları | Infra | Namespace ve cluster'a göre uyarı / hata, en gürültülü container'lar |

Network panosundaki başarılı istek sayıları örneklenmiştir: başarılı istekler 1/10 tutulur, hata ve redler tamdır (10 · logging). Panoların açıklamalarında bu belirtiliyor.

## Önceki adıma göre değişenler

| Değişiklik | Neden |
|------------|-------|
| `manifests/mgmt/36-keycloak-admin.yaml`: NodePort servisi (ingress gateway, 30808), Gateway (8081), VirtualService (`/`, `/admin`, `/admin/` → konsol), AuthorizationPolicy (yalnızca yönetim yolları) | Komutsuz yönetim erişimi; uygulama realm'leri bu kapıdan kapalı |
| `clusters/mgmt.yaml`: `30808 → 127.0.0.1:8081` | Yalnızca bu makine |
| `KC_HOSTNAME_ADMIN` 8080 → 8081; master `frontendUrl` 8081; `KEYCLOAK_ADMIN_PORT` (config.env) | Port-forward'ın yerine kalıcı adres |
| `infra/logging/dashboards/` (6 pano + üreteç); 07b panoları yükler, yöneticiyi ekip organizasyonlarına ekler | Loki panoları |
| 07b: Grafana API gövdesi stdin'den | Windows'ta komut satırı argümanı kod sayfasına çevriliyor, ü / ı / · bozuluyordu |
| Fluent Bit: `json.escape_unicode Off` | Türkçe metinler satırda `İ` olarak kaçışlanıyordu; "İZİN", "PERSONEL ERİŞİMİ" filtreleri eşleşmiyordu |
| Doğrulama: "14) Yönetim arayüzleri" | – |

## Tasarım kararları

- **Ayrı NodePort değil, ingress gateway'in dinleyicisi.** Keycloak'ın namespace'i mesh'te ve L4'te yalnızca ingress gateway kimliğine açık. Yönetim trafiği de gateway'den geçince bu kural değişmeden kalır. Yol kısıtı gateway'de L7 olarak uygulanır.
- **Yalnızca 127.0.0.1.** Konsolun ağ seviyesindeki tek koruması bu ve Keycloak'ın kendi girişi. Gerçekte yönetim arayüzlerine bastion / PAM üzerinden, ayrı bir yönetim ağından, MFA ile erişilir.
- **Panolar kodda.** JSON'u bir üreteç yazar; elle düzenlenen pano kalıcı olmaz. Sıfırdan kurulumda aynı panolar gelir.

## STRIDE (yeni ve değişen akışlar)

| Akış | Tehdit | Senaryo | Kontrol | Durum |
|------|--------|---------|---------|-------|
| Yönetim konsolu | **S**poofing | Ağdaki başka bir cihaz konsola bağlanır | Port yalnızca 127.0.0.1 (test) | ✅ |
| | **E**levation of privilege | Yönetim kapısından uygulama realm'lerine erişim | Gateway'de yalnızca yönetim yolları (test: 403) | ✅ |
| | **E**levation of privilege | İnternetten yönetim konsoluna erişim | DMZ'de `/admin` ve master realm kapalı (test: 403) | ✅ |
| | **S**poofing | Admin parolası ele geçirilir | Tek faktör (lab) | ⚠️ MFA yok |
| | **I**nformation disclosure | Konsol trafiği düz HTTP | Yalnızca makine içi (127.0.0.1); gateway → Keycloak mTLS | ⚠️ lab |
| Panolar | **I**nformation disclosure | Ekip başka ekibin panosunu görür | Panolar ekip organizasyonunda (test: soc01 yalnızca Security) | ✅ |

## Karşılaşılan sorunlar ve çözümler

| # | Sorun | Neden | Çözüm |
|---|-------|-------|-------|
| 1 | Gateway reddedildi: "short names (non FQDN) are not allowed" | Istio Gateway host'unda `localhost` kabul etmiyor | Dinleyici `*`; Host kısıtı (`localhost`) AuthorizationPolicy'de |
| 2 | Gateway üzerinden `/admin/` 404 | Keycloak bu kökü gateway arkasında yönlendirmiyor (doğrudan erişimde 302) | VirtualService: `/`, `/admin`, `/admin/` → `/admin/master/console/` |
| 3 | Pano başlıkları ve veri kaynağı adları bozuk (`�`) | Windows'ta curl'e argüman olarak verilen gövde kod sayfasına çevriliyor | Gövde stdin'den (`--data-binary @-`); başlıklarda ASCII ayırıcı (`-`) |
| 4 | Türkçe metinli paneller boş (İZİN, PERSONEL ERİŞİMİ) | Fluent Bit JSON'da Unicode'u kaçışlıyor | `json.escape_unicode Off` |

## Doğrulama

Sıfırdan kurulum: `99-destroy.sh` → `setup.sh` (içinde `08-verify.sh`), tek seferde, elle müdahale yok. **Süre: ~38 dk.** **Sonuç: 250 başarılı, 0 başarısız.**
- 240'tan 250'ye: 10 yeni test ("14) Yönetim arayüzleri"). Önceki adımların testleri değişmeden geçiyor.

Bu adımda eklenen testler (`08-verify.sh` → "14) Yönetim arayüzleri"):

| Test | Beklenen | Sonuç |
|------|----------|-------|
| Yönetim portu yalnızca 127.0.0.1 | `127.0.0.1:8081` | ✔ |
| `/admin` konsola; konsolun giriş adresi localhost; master realm ile yönetici girişi | – | ✔ ✔ ✔ |
| Yönetim kapısından uygulama realm'i; edge'den konsol | 403 / 403 | ✔ ✔ |
| Genel bakış panosu; soc01 yalnızca Security panosu | – | ✔ ✔ ✔ |
| Loglarda Türkçe metin aranabiliyor | – | ✔ |

Pano sorgularının tamamı (50 panel sorgusu) çalışan ortamda Grafana üzerinden Loki'ye sorduruldu: hatalı sorgu yok.

## Bilinen kısıtlar

- Yönetim konsolu tek faktörlü (admin parolası) ve düz HTTP. Ağ koruması yalnızca 127.0.0.1. Gerçekte bastion / PAM, MFA ve TLS gerekir.
- Grafana'da da (http://localhost:3001) aynı durum: girişli ama tek faktörlü.
- Panolarda alarm yok; korelasyon kuralları ve alarmlar SIEM işi (SOC-04).
