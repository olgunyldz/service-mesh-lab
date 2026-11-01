# 09a · IdP tabanlı token exchange, web oturumu ve internal BFF

| | |
|---|---|
| **Branch** | `idp-token-exchange` (açıldığı yer: `token-exchange`) |
| **Durum** | ✅ Tamamlandı, sıfırdan kurulumla doğrulandı (150/150 test) |

## Amaç

Kurumsal hedef mimari dokümanındaki üç kararı lab'e taşımak:
- **İç JWT'yi IdP üretir** (GW-03, IAM-05):
  - DMZ dış token'ı IdP'de introspect eder ve RFC 8693 token exchange ile iç JWT'yi Keycloak'tan alır.
  - DMZ'de imza anahtarı kalmaz.
- **İç JWT ≤ 2 dk** olur ve `acr`, `sid`, `scope` gibi claim'leri taşır. Kanala özel claim'ler (`partner_id`, `branch_id`) de IdP'den gelir.
- **BFF internal'da, DMZ'de iş mantığı yok** (INT-07, GW-09):
  - Web kanalında tarayıcı hiç token görmez; elinde yalnızca oturum cookie'si vardır (CH-06, GW-07).
  - Cookie'yi token'a DMZ'deki `web-token-handler` çevirir.
  - Ekran birleştirme işini internal'daki `web-bff` yapar.

## Adım sonundaki durum

| Konu | Durum |
|------|-------|
| İç JWT | **Keycloak imzalı** (realm başına issuer: `customers`, `partners`, `staff`), `aud=internal-apis`, **120 sn**. Claim'ler: `sub`, `channel`, `acr`, `sid`, `roles`, `scope` (+ `partner_id`, `branch_id`). Kişisel veri (ad, e-posta) yok |
| auth-service 0.2.0 (DMZ, `auth`) | Dokümandaki `auth-proxy`. Sırasıyla: `iss` ön kontrolü → **introspection** → kanal kuralları → **token exchange** (kanal başına exchange client'ı) → iç JWT. İç JWT en fazla 30 sn önbellekte; aynı token için eşzamanlı istekler tek IdP çağrısında birleşir. İmza anahtarı yok |
| Dış token'lar | **Lightweight**: içinde yalnızca `iss`, `aud`, `azp`, `sid`, `exp`; rol ve kişisel veri yok (içerik yalnızca introspection'da). `aud` = kanalın exchange client'ı (ör. mobil token'ı yalnızca `auth-mobile` çevirebilir) |
| Web kanalı | `web-token-handler` 0.1.0 (DMZ, `edge-web`): sunucu tarafında Authorization Code + PKCE (`web-app` gizli client). Oturum mgmt Valkey'de (`sess:*`, ayrı ACL kullanıcısı). Tarayıcıda yalnızca `__Host-sid` (HttpOnly, Secure, SameSite=Strict). Diğer korumalar: CSRF header'ı, idle 15 dk / absolute 8 saat, refresh token rotation, logout'ta IdP oturumu da kapanır. Web gateway'de bearer token kabul edilmez |
| BFF | `web-bff` 0.3.0 artık **internal'da** (cluster-a, `channel-bff`). Yol: token handler → DMZ egress → int-ingressgw (`web-bff.apps.example.local`) → web-bff → api-a / account-api. DMZ'deki `web-bff` namespace'i kaldırıldı |
| Internal | RequestAuthentication: 3 issuer, inline JWKS (realm açık anahtarları kurulumda biliniyor). `requestPrincipals` 3 realm'e göre. web-bff yalnızca `channel=web` ve customers realm'inin JWT'siyle çağrılabilir |
| Mobil, partner, şube | Yolları aynı (gateway → ext_authz → egress → internal); doğrulama artık introspection + exchange. mobile-bff ve branch-bff sonraki adımlarda |

## Önceki adıma göre değişenler

| Değişiklik | Neden |
|------------|-------|
| auth-service: kendi imzası yerine introspection + Keycloak token exchange | Doküman kararı: iç JWT'yi IdP üretir. DMZ ele geçirilse bile içeri girecek kimliği DMZ uyduramaz |
| Realm'lerde kanal başına exchange client'ı (`auth-web`, `auth-mobile`, `auth-partner`, `auth-branch`) ve `internal-apis` audience client'ı | `channel` claim'ini exchange client'ının sabit claim'i koyar: kanal bilgisi IdP'de imzalanır. Exchange client'ı başka kanalın token'ını çeviremez (dış token'ın `aud`'unda değil) |
| Dış token'lar lightweight, `aud` = kanalın exchange client'ı | Phantom token'a yakın davranış: dış token'dan rol ve kişisel veri okunamaz. Token yanlış kanala götürülse bile çevrilemez |
| Realm imza anahtarları kurulumda üretiliyor (`certs/idp/`), realm'e rsa key provider ile veriliyor | Internal açık anahtarı baştan bilir: kurulum sırasına ve internal'dan IdP'ye ağ çağrısına bağımlılık yok |
| `certs/auth/` (DMZ imza anahtarı), `INTERNAL_JWT_ISSUER`, `auth-signing-key` Secret'ı kaldırıldı | DMZ'de anahtar kalmadı |
| İç JWT ömrü 5 dk → 2 dk; exchange client'larında minimal scope (`basic`, `acr`, `roles`) | IAM-05; iç JWT'de ad/e-posta gibi kişisel veri olmasın (veri minimizasyonu) |
| Web: `web-token-handler` (DMZ), `web-app` gizli client; web gateway'de ext_authz kaldırıldı, `Authorization` siliniyor | CH-06: tarayıcı token görmez. Cookie'yi oturuma çeviren handler, auth-service'e kendisi sorar |
| `web-bff` DMZ'den internal'a (`channel-bff`), 0.3.0: hesap uçları account-api'ye, gerisi api-a'ya | GW-09 / INT-07: DMZ'de iş mantığı olmasın |
| Egress: `allow-channel-backends`'te web-bff waypoint'i yerine edge-web waypoint'i; `web-bff.apps.example.local` çıkışı; SSO çıkışında POST token/introspect/logout; Valkey çıkışına edge-web | Yeni akışlar, yalnızca gereken uç ve metotlarla |
| Valkey ACL: `web_session` kullanıcısı (yalnızca `sess:*`, yalnızca GET/SET/DEL) | Oturum deposu ratelimit ve api-a anahtarlarından ayrı |
| account-api 0.3.0 | Log'da `branch_device` yerine `branch_id`, `sid` eklendi |
| Keycloak Deployment'ı `strategy: Recreate` | Tek replikada rolling update kilitleniyordu (bkz. sorunlar) |
| loadgen web'de tarayıcı gibi giriş yapıyor; token yenilemesi zamana bağlı | Web'de token yok; tur süresi uzayınca token'lar süresi dolmuş kullanılıyordu |
| ext_authz zaman aşımı 2 sn → 4 sn | Önbellekte değilse iki IdP çağrısı (introspection + exchange) |

## Eklenen bileşenler

| Bileşen | Amacı | Neden gerekli | Muadilleri | Neden bu seçildi |
|---------|-------|---------------|------------|------------------|
| **Keycloak standard token exchange (V2, RFC 8693)** | Dış access token → iç JWT | İç JWT'yi IdP üretsin (doküman kararı) | Keycloak legacy exchange (V1, preview; realm'ler arası), JWT Authorization Grant (RFC 7523), Curity, PingFederate (STS), WSO2 IS, Auth0 Custom Token Exchange | Keycloak 26'da destekli (preview değil). Realm içinde çalıştığı için realm başına exchange client'ı + 3 issuer; avantajı, internal'ın token'ın hangi realm'den geldiğini issuer'dan okuyabilmesi |
| **Token introspection (RFC 7662) + lightweight access token** | Dış token'ın IdP'de doğrulanması | Oturum iptali dış token'ı hemen geçersiz kılsın; dış token içerik taşımasın (phantom token) | Yerel JWKS doğrulaması (08), opak token (Curity), Keycloak lightweight token | Introspection, iptal edilen oturumu yakalar (yerel doğrulama yakalayamaz). Lightweight token, Keycloak'ın gerçek opak token'a en yakın seçeneği |
| **web-token-handler** (Go, stdlib) | Web kanalında cookie ↔ token (OAuth token handler / BFF-for-tokens deseni) | CH-06: tarayıcıda token olmasın (XSS ile token çalınamaz) | Curity Token Handler, oauth2-proxy, Spring Security OAuth2 Client (dokümandaki aday), Duende BFF (.NET), Envoy `oauth2` filtresi | Bağımlılıksız, küçük. Akışın her adımı (PKCE, state, nonce, rotation, CSRF) açıkça görülüyor ve test ediliyor. oauth2-proxy token handler değil, kimlik proxy'si; Envoy `oauth2` filtresi token'ı cookie'de taşıyor |
| **Oturum deposu** (mgmt Valkey, `sess:*`) | Token'ların sunucu tarafında saklanması | Cookie'de yalnızca rastgele oturum kimliği olsun; çok replikada ortak oturum | Redis/Valkey (kimlik zone'unda ayrı), Infinispan, şifreli cookie (stateless) | Mevcut Valkey, ayrı ACL kullanıcısıyla. Anahtar cookie değerinin hash'i: depo sızsa bile cookie üretilemez |
| **channel-bff** (internal namespace) | Kanal BFF'lerinin yeri | DMZ'de iş mantığı olmasın; BFF iç JWT ile, internal politikalarının arkasında çalışsın | BFF'yi DMZ'de bırakmak (08), API gateway'de birleştirme (GraphQL federation) | Dokümanla aynı yerleşim; DMZ ele geçirilse bile iş mantığına erişim yok |

## Yapılanlar

### İstek akışı (mobil, partner, şube)

```
istemci --Bearer (lightweight)--> kanal gateway'i --ext_authz--> auth-service
  auth-service: iss ön kontrolü -> introspection (Keycloak) -> kanal kuralları -> token exchange (Keycloak)
  <-- x-user-jwt (Keycloak imzalı, 2 dk) -- gateway Authorization'ı siler --> dmz-egress --> internal
```

**auth-service kontrol sırası:**
1. `Authorization: Bearer` var mı? Yoksa **401**.
2. `iss` kanalın realm'i mi? Değilse **403**. İmzasız ön okuma; başka realm'in token'ı IdP'ye hiç gönderilmez.
3. Introspection (kanalın exchange client'ının kimliğiyle):
   - `active` değilse **401**. İmza tutmuyorsa, süresi dolmuşsa ya da oturum kapatılmışsa token aktif değildir.
   - `typ=Bearer` olmalı.
4. Kanal kuralları:

   | Kanal | Kural |
   |-------|-------|
   | Hepsi | `azp` doğru client olmalı |
   | Partner | `azp` = sertifika CN'i |
   | Şube | Cihaz sertifikası olmalı |

   Ayrıca rol kontrolü yapılır. İhlal durumunda **403**.
5. Token exchange (`audience=internal-apis`). Keycloak reddederse **403**.
6. Şube: iç JWT'deki `branch_id` (personelin IdP'deki şubesi) cihaz sertifikasıyla eşleşmeli. Eşleşmezse **403**.
7. Sonuç `min(30 sn, exp − 10 sn)` süreyle önbelleğe alınır. Aynı anahtar için süren bir IdP çağrısı varsa yeni istekler onu bekler (singleflight).

**Exchange client'ları:**

| Realm | Dış client (`azp`) | Dış token `aud` | Exchange client | `channel` | Ek claim |
|-------|--------------------|-----------------|-----------------|-----------|----------|
| `customers` | `web-app` (gizli, token handler) | `auth-web` | `auth-web` | `web` | – |
| `customers` | `mobile-app` (public, PKCE) | `auth-mobile` | `auth-mobile` | `mobile` | – |
| `partners` | `acme`, `initech` (client credentials) | `auth-partner` | `auth-partner` | `partner` | `partner_id` (grup attribute'u) |
| `staff` | `branch-teller` (public, PKCE) | `auth-branch` | `auth-branch` | `branch` | `branch_id` (grup attribute'u) |

Exchange client'larının ayarları:
- `standard.token.exchange.enabled: true` ve `access.token.lifespan: 120`.
- Varsayılan scope'lar yalnızca `basic`, `acr` ve `roles`.
- Mapper'lar: audience `internal-apis`, sabit `channel`, düz `roles` listesi.

**İç JWT örneği (mobil):**

```json
{ "iss": "https://sso.apps.example.local:8443/realms/customers", "aud": "internal-apis", "azp": "auth-mobile",
  "sub": "…", "sid": "…", "acr": "1", "roles": ["customer"], "channel": "mobile", "scope": "",
  "iat": 1793528857, "exp": 1793528977, "jti": "…" }
```

`scope` şimdilik boş. API scope'ları (`accounts:read`, `transfers:write`) ve `acr` seviyeleri 09b'de tanımlanacak.

### Web oturumu (token handler)

| Uç | Ne yapar |
|----|----------|
| `GET /auth/login` | `state`, `nonce` ve PKCE `verifier` üretir; oturum deposuna yazar (5 dk). `state`'i `__Host-login` cookie'siyle tarayıcıya bağlar (login CSRF). Keycloak'a yönlendirir |
| `GET /auth/callback` | `state` cookie ile eşleşmeli, tek kullanımlık. `code` sunucu tarafında token'a çevrilir (gizli client + `code_verifier`). `nonce` kontrol edilir. Oturum açılır, `__Host-sid` yazılır |
| `GET /auth/session` | Oturum durumu ve CSRF token'ı (SPA için) |
| `POST /auth/logout` | CSRF ister. IdP oturumunu kapatır (arka kanal logout), oturumu siler, cookie'yi temizler |
| `/api/*` | Cookie → oturum → (gerekirse refresh, oturum başına kilitli) → auth-service (kanal: web) → iç JWT → web-bff. `/api` öneki düşer. Yalnızca izinli header'lar geçer: cookie, `Authorization`, sahte `x-user-jwt` ve `X-Forwarded-For` geçmez. Durum değiştiren metotlarda `X-CSRF-Token` zorunlu |
| `/`, `/healthz` | Küçük statik sayfa (lab'de web-static yerine), sağlık kontrolü |

Oturum şu durumlarda biter:
- 15 dk hareketsizlik (Valkey TTL'i her istekte yenilenir).
- Açıldıktan 8 saat sonra (absolute timeout).
- Logout.
- Refresh başarısız olursa (ör. IdP'de oturum kapatıldıysa).

Refresh token her kullanımda yenilenir (realm: `revokeRefreshToken`, tekrar kullanım 0).

### Internal

- int-ingressgw'de yeni host: `web-bff.apps.example.local`. Aynı SNI ile gelir, Host'a göre ayrılır.
- `channel-bff` waypoint'inde web-bff'e erişim şartı:
  - Yalnızca int-ingressgw kimliğinden gelen istek.
  - customers realm'inin JWT'si.
  - `channel=web` claim'i.
- api-a ve account-api, int-ingressgw'ye ek olarak web-bff kimliğini de kabul eder. JWT her waypoint'te yeniden doğrulanır.

## Değişen dosyalar

| Dosya | Değişiklik |
|-------|------------|
| `services/web-token-handler/` | **Yeni.** Go kodu (token handler + küçük Valkey istemcisi), Dockerfile, go.mod |
| `services/auth-service/` | 0.2.0: introspection + token exchange, `iss` ön kontrolü, singleflight; imza kodu kaldırıldı |
| `services/web-bff/` | 0.3.0: internal'da; `/accounts*` → account-api |
| `services/account-api/` | 0.3.0: log'da `branch_id`, `sid` |
| `infra/keycloak/realm-*.json` | Exchange client'ları, `internal-apis`, `web-app`, lightweight dış token'lar, realm imza anahtarı, gruplar (`partner_id`, `branch_id`), rotation |
| `manifests/dmz/10-web-token-handler.yaml` | **Yeni** (`10-web-bff.yaml` kaldırıldı). Handler + Keycloak, Valkey, web-bff çıkışları + AuthZ |
| `manifests/dmz/00-namespaces.yaml`, `12-auth-service.yaml`, `20-public-gateway.yaml`, `27-ext-authz.yaml`, `30-internal-clusters.yaml` | `edge-web`; auth-service secret'ları ve IdP çıkışı; web rotası handler'a; web ext_authz'ı kaldırıldı; egress kuralları |
| `manifests/cluster-a/16-channel-bff.yaml` | **Yeni.** web-bff (internal), waypoint, AuthZ |
| `manifests/cluster-a/00-namespaces.yaml`, `15-account-api.yaml`, `30-internal-gateway.yaml`, `40-security.yaml`, `45-request-authentication.yaml` | `channel-bff`; 3 issuer; web-bff kimliği; web-bff host'u |
| `manifests/mgmt/30-keycloak.yaml` | `strategy: Recreate` |
| `istio/values/istiod-dmz.yaml` | `auth-web` sağlayıcısı kaldırıldı, zaman aşımı 4 sn |
| `scripts/03-generate-certs.sh`, `05b-create-data-secrets.sh`, `lib.sh` | Realm anahtarları + JWKS; exchange ve handler secret'ları, Valkey `web_session`; `__IDP_JWKS_<realm>__` |
| `scripts/06b-deploy-edge.sh`, `08-verify.sh`, `tests/web-login.sh` | loadgen tarayıcı gibi giriş; web testleri cookie ile; yeni kimlik ve oturum testleri |
| `config.env` | Build sürümleri, `WEB_BFF_HOST`; `INTERNAL_JWT_ISSUER` kaldırıldı |

## Tasarım kararları

- **Realm başına exchange client'ı ve 3 issuer.**
  - Keycloak V2 exchange yalnızca realm içinde çalışıyor.
  - Tek issuer için iki yol vardı: realm'ler arası V1 exchange (preview, fine-grained admin permissions) ya da realm'leri birleştirmek (IAM-09'a aykırı). İkisi de seçilmedi.
  - 3 issuer'ın bir faydası da var: internal'da issuer, token'ın hangi kullanıcı tipinden geldiğini zaten söylüyor.
- **`channel` claim'ini IdP koyar.** Exchange client'ı kanala özgü olduğu için DMZ'deki bir hata ya da saldırgan kanalı değiştiremez; claim imzalı.
- **Introspection her istekte değil, 30 sn önbellekli.**
  - Hedef "iptal ≤ 5 sn" (IAM-07) ise ya önbellek kısaltılmalı ya da Keycloak'ın oturum olayları dinlenip önbellek temizlenmeli (sonraki adım).
  - Önbellek yalnızca auth-service'in belleğinde. Çok replikada her replika kendi önbelleğini tutar; IdP'ye yük replika sayısıyla artar.
- **Web'de ext_authz gateway'de değil handler'da.** Tarayıcıdan token gelmiyor; cookie'yi token'a çevirmek handler'ın işi. Handler auth-service'e `x-auth-channel: web` ile sorar. Bu header'ı yalnızca handler ve kanal gateway'leri gönderebilir (auth-service L4 AuthZ).
- **Oturum anahtarı = SHA-256(cookie).** Valkey dökümü sızsa bile geçerli cookie üretilemez.
- **Realm imza anahtarı kurulumda üretiliyor.** Gerçekte HSM'de durur ve Keycloak'a HSM üzerinden verilir. Lab'de diskte (`certs/idp/`, git'e girmez).
- **İç JWT'de kişisel veri yok.** Internal servisler kullanıcıyı `sub` ile tanır; ad ve e-posta gerekiyorsa müşteri servisinden alınır (KVKK, veri minimizasyonu).

## STRIDE (yeni ve değişen akışlar)

| Akış | Tehdit | Senaryo | Kontrol | Durum |
|------|--------|---------|---------|-------|
| Tarayıcı → web | **I**nformation disclosure | XSS ile token çalınır | Tarayıcıda token yok; cookie HttpOnly (test: girişte yanıtlarda token yok, yalnızca `__Host-sid`) | ✅ |
| | **S**poofing | CSRF ile kullanıcı adına işlem | SameSite=Strict + `X-CSRF-Token` (test: header'sız POST 403) | ✅ |
| | **S**poofing | Login CSRF / code enjeksiyonu | `state` cookie'ye bağlı ve tek kullanımlık, PKCE, `nonce` | ✅ |
| | **S**poofing | Sahte / tahmin edilen cookie | 256 bit rastgele kimlik (test: sahte cookie 401) | ✅ |
| | **R**epudiation / oturum kalıcılığı | Çıkıştan sonra cookie tekrar kullanılır | Logout oturumu ve IdP oturumunu siler (test: 401) | ✅ |
| Kanal → DMZ | **E**levation of privilege | Bir kanalın token'ı başka kanalda | Dış token'ın `aud`'u yalnızca kendi exchange client'ı; `iss` ön kontrolü; `azp` kuralı (test: mobil token web'de 401, partner'da ve şubede 403) | ✅ |
| | **S**poofing | Kapatılmış oturumun token'ı kullanılır | Introspection (test: IdP'de kapatılan oturum 30 sn içinde 401) | ✅ |
| | **D**enial of service | Aynı token'la eşzamanlı istekler IdP'yi boğar | Singleflight + 30 sn önbellek | ✅ |
| DMZ → internal | **S**poofing | DMZ ele geçirilir, sahte iç JWT üretilir | DMZ'de imza anahtarı yok; internal yalnızca Keycloak realm anahtarlarına güveniyor (test) | ✅ |
| | **E**levation of privilege | DMZ kanal bilgisini değiştirir | `channel` IdP'nin imzaladığı claim; web-bff yalnızca `channel=web` kabul ediyor | ✅ |
| | **I**nformation disclosure | İç JWT'de kişisel veri | Minimal scope (test: ad ve e-posta yok) | ✅ |
| Şube | **S**poofing | Personel başka şubenin cihazından işlem yapar | `branch_id` (IdP) = cihaz sertifikası (test) | ✅ |
| Oturum deposu | **I**nformation disclosure | Valkey dökümünden oturum çalınır | Anahtar cookie'nin hash'i; ayrı ACL kullanıcısı (test) | ⚠️ token'lar depoda şifresiz (gerçekte şifreli alan ya da ayrı kimlik zone'u) |
| IdP | **D**enial of service | Keycloak erişilemez | Fail-closed; önbellekteki iç JWT'ler en fazla 30 sn çalışır | ⚠️ tek replika |

## Karşılaşılan sorunlar ve çözümler

| # | Sorun | Neden | Çözüm |
|---|-------|-------|-------|
| 1 | Lightweight dış token'la exchange 403 "Client is not within the token audience" | Lightweight token `aud`'u da atıyor | Audience mapper'da `lightweight.claim: true` (denemeyle bulundu) |
| 2 | İç JWT'de ad, soyad, e-posta | Exchange client'larında varsayılan `profile`/`email` scope'ları | `defaultClientScopes: [basic, acr, roles]` |
| 3 | Keycloak güncellemesi bitmiyor, yeni pod hiç hazır olmuyor | Tek replikada rolling update: yeni pod eskisini cluster üyesi olarak görüyor, pod'lar arası Infinispan trafiği mesh'te kapalı ("cluster health check DOWN") | `strategy: Recreate` |
| 4 | Çalışan ortamda Keycloak yeni realm tanımını almadı | `--import-realm` mevcut realm'i atlıyor (`IGNORE_EXISTING`) | Yükseltmede realm'ler silinip yeniden içe aktarıldı; sıfırdan kurulumda sorun yok |
| 5 | Web istekleri gateway'de 403 (`deny-due-to-bad-CUSTOM-action`) | Dosyadan kaldırılan web ext_authz politikası kümede duruyordu (`kubectl apply` silmez) | Elle silindi; sıfırdan kurulumda yok |
| 6 | Token handler → web-bff 503 (`connection_termination`) | int-ingressgw web-bff pod'una doğrudan bağlandı (waypoint'i atladı), pod'un L4 kuralı yalnızca waypoint'e izin veriyor | Service'e `istio.io/ingress-use-waypoint: "true"` (api-a ve account-api'deki gibi) |
| 7 | Müşteri token'ı partner ve şube kanalında 403 yerine 401 | Başka realm'in introspection'ı token'ı "aktif değil" sayıyor | Introspection'dan önce imzasız `iss` ön kontrolü: 403 ve yabancı token IdP'ye hiç gitmiyor |
| 8 | Kota testlerinde 429 yerine 503, IdP çağrılarında zaman aşımı | Önbellek boşken aynı token'la gelen 30 eşzamanlı istek, 60 IdP çağrısı | Singleflight: eşzamanlı istekler tek çağrıyı bekliyor |
| 9 | Yeniden build edilen auth-service'in eski kodu çalışmaya devam etti | Kyverno digest'i Deployment şablonuna yazıyor; aynı etiketle build + `rollout restart` eski digest'i kullanıyor | Manifest yeniden uygulanınca etiket yeni digest'e çözülüyor. Ders: etiketi değiştirmeden yeniden build etmek güvenilir değil |
| 10 | loadgen'in mobil ve partner token'ları süresi dolmuş | Yenileme tur sayısına bağlıydı; turlar 1 sn'den uzun sürünce 5 dk'lık token yenilenmeden doluyordu | Yenileme zamana bağlı (200 sn) |
| 11 | loadgen betiği çalışmadı | Tek tırnaklı betikteki yorumda kesme işareti ("Keycloak'ta") tırnağı kapatıyordu | Yorum değiştirildi |
| 12 | Değiştirilmiş token testi 200 döndü | Lightweight token'da `sub` yok; test `sub`'ı değiştirdiği için token aynı kalıyordu | Test `jti`'yi değiştiriyor (401) |
| 13 | Doğrulama betiği ortada sonlanıyordu | `grep -c` eşleşme bulamayınca çıkış kodu 1, `set -e` betiği durduruyor | `|| true` |

## Doğrulama

Sıfırdan kurulum: `99-destroy.sh` → `setup.sh` (tek seferde, elle müdahale yok). **Süre: ~23 dk.** **Sonuç: 150 başarılı, 0 başarısız.**
- Önceki adımların testleri web'de cookie ile, diğer kanallarda yeni exchange akışıyla geçiyor.
- Kurulumdan önce çalışan ortama da uygulandı ve aynı test seti 150/150 geçti. Yükseltmede yaşanan sorunlar yukarıdaki tabloda (4, 5, 9 numaralı satırlar).

Kaynak kullanımı (kurulumdan hemen sonra, node başına): mgmt ~3,2 GB, cluster-a ~2,4 GB, dmz ~2,5 GB. Yeni bileşenlerin ek maliyeti küçük: token handler ve web-bff 64 MB sınırlı, birer waypoint daha (edge-web, channel-bff).

Bu adımda eklenen ve değişen testler:

| Test | Beklenen | Sonuç |
|------|----------|-------|
| Web oturumu, mobil, partner ve personel token'ı alınabiliyor | 4 | ✔ |
| Web: giriş Authorization Code + PKCE; tarayıcıda yalnızca `__Host-sid` | – | ✔ |
| Web: cookie HttpOnly, Secure, SameSite=Strict | – | ✔ |
| Web: giriş boyunca tarayıcıya giden yanıtlarda token | 0 | ✔ |
| Web: CSRF header'sız POST / sahte cookie | 403 / 401 | ✔ ✔ |
| Web: logout 204, sonra aynı cookie | 204 / 401 | ✔ ✔ |
| Web: token handler (DMZ) ve web-bff (internal) imzalı image; DMZ'de BFF yok | – | ✔ ✔ ✔ |
| Web gateway'den token handler'ı atlayıp egress'e çıkış | 403 | ✔ |
| Oturumsuz web isteği; web'de bearer token | 401 / 401 | ✔ ✔ |
| Müşteri token'ı şube ve partner kanalında | 403 / 403 | ✔ ✔ |
| Değiştirilmiş token | 401 | ✔ |
| Dış token lightweight (rol / kişisel veri yok), `aud` = `auth-mobile` | – | ✔ ✔ |
| İç JWT: Keycloak imzalı (`iss` = customers realm'i), `aud`, `channel=web`, `acr` + `sid`, ömür ≤ 2 dk, kişisel veri yok | – | ✔ ✔ ✔ ✔ ✔ ✔ |
| İç JWT (partner): `partner_id=acme`; (şube): `branch_id` = cihaz | – | ✔ ✔ |
| IdP'de kapatılan oturumun token'ı 30 sn içinde | 200 → 401 | ✔ |
| Oturum deposu: yalnızca `sess:` öneki, cookie anahtarda yok; `web_session` başka öneki okuyamıyor | – | ✔ ✔ |
| Internal yalnızca Keycloak issuer'larına güveniyor; DMZ imza anahtarı hiçbir cluster'da yok | – | ✔ ✔ |
| Pod Security: `edge-web` (dmz), `channel-bff` (cluster-a) | restricted, ihlal yok | ✔ ✔ |

## Bilinen kısıtlar

- `device_id` iç JWT'de yok: istek anındaki cihaz kimliğini (sertifika, DPoP anahtarı) Keycloak bilemiyor. Şubede cihaz kontrolü DMZ'de yapılıyor ve `branch_id` ile eşleştiriliyor. Mobilde DPoP ve cihaz bağlama sonraki adımlarda.
- `scope` boş, `acr` hep `1`: API scope'ları ve doğrulama seviyeleri (step-up) 09b'de.
- Oturum iptali en geç 30 sn'de etkili (hedef ≤ 5 sn: Keycloak oturum olaylarıyla önbellek temizliği).
- Oturum deposu mgmt'teki Valkey'de; hedefte kimlik zone'unda ayrı `redis-session`. Token'lar depoda şifrelenmiyor.
- web-token-handler ve auth-service tek replika. Refresh kilidi işlem içi; çok replikada dağıtık kilit gerekir.
- mobile-bff ve branch-bff yok; mobil, partner ve şube doğrudan api-a / account-api'ye gidiyor.
- Web statik içerik ayrı bir `web-static` değil, handler'ın küçük sayfası.
- Realm imza anahtarları diskte; HSM yok. Anahtar rotasyonu elle (yeni anahtar JWKS'e eklenip eskisi bir süre tutulmalı).
- Direct grant (ROPC) mobil ve personel test client'larında açık (yalnızca lab); web'de kapalı.
