# 08 · Kimlik ve Token Exchange (Keycloak, auth-service, iç JWT)

| | |
|---|---|
| **Branch** | `token-exchange` (açıldığı yer: `data`) |
| **Durum** | ✅ Tamamlandı, sıfırdan kurulumla doğrulandı (131/131 test) |

## Amaç

Sisteme kullanıcı kimliğini katmak:
- Her kanal bir access token ister.
- Token DMZ'de doğrulanır ve **dış token DMZ'de bırakılır**.
- İçeriye yalnızca DMZ'nin imzaladığı kısa ömürlü bir **iç JWT** girer.
- Internal servisler kullanıcıyı (`sub`, roller, kanal, partner veya cihaz) bu JWT'den tanır.
- Internal taraf JWT'siz hiçbir isteği kabul etmez.

## Adım sonundaki durum

| Konu | Durum |
|------|-------|
| Kimlik sağlayıcı | **Keycloak 26.8** (mgmt, `iam` namespace'i), optimize image, veritabanı mgmt PostgreSQL'i. Realm'ler: `customers`, `partners`, `staff` |
| Login / token | `sso.apps.example.local` → edge → web gateway → dmz-egress → mgmt ingress → Keycloak. Personel için şube gateway'inden `/sso/realms/staff/*`. **Yönetim konsolu ve master realm dışarıya kapalı** |
| auth-service | DMZ `auth` namespace'i, Go (yalnızca stdlib), imzalı image. Envoy ext_authz servisi: dış token'ı doğrular, iç JWT'yi imzalar (RS256, ≤ 5 dk) |
| Kanal gateway'leri | 4 gateway'de `CUSTOM` AuthorizationPolicy (kanal başına ayrı ext_authz sağlayıcısı). `Authorization` silinir, `x-user-jwt` eklenir |
| Internal | cluster-a'da `RequestAuthentication` (inline JWKS, ingress + waypoint'ler). AuthZ'lerde `requestPrincipals` zorunlu; account-api'de rol kontrolü |
| Servisler | web-bff 0.2.0 (`x-user-jwt`'yi taşır), account-api 0.2.0 (kullanıcıyı loglar) |
| Kaynak | Kullanılabilir bellek ~3,25 GB: Keycloak eklendiği halde 07'deki seviye (bkz. kaynak sorunu) |

## Önceki adıma göre değişenler

| Değişiklik | Neden |
|------------|-------|
| mgmt'e Keycloak (`iam`), realm'ler kod olarak (`infra/keycloak/realm-*.json`) | Kanal başına kimlik: müşteri, partner, personel. Yapılandırma tekrarlanabilir olsun |
| DMZ'ye auth-service ve kanal gateway'lerinde ext_authz | Token doğrulama ve token exchange tek yerde, DMZ'de |
| İç JWT imza anahtarı (`certs/auth/`), yalnızca DMZ'de Secret | İçeriye girecek kimliği yalnızca DMZ üretebilsin |
| cluster-a'da RequestAuthentication + `requestPrincipals` | Internal, iç JWT'siz isteği reddetsin; JWT her waypoint'te yeniden doğrulansın |
| Kanal VirtualService'lerinde `Authorization` siliniyor | Dış token internal'a sızmasın |
| SSO rotaları (web gateway `sso` host'u, şube `/sso/`), egress `allow-sso-exit`, mgmt `keycloak-entry` | Kullanıcı ve personel login'i; auth-service'in JWKS çağrısı. Web gateway'in API host'larına çıkışı yine kapalı |
| Şube gateway'inde `forwardClientCertDetails: SANITIZE_SET` | Cihaz sertifikası bilgisi (XFCC) ext_authz'ye ulaşsın; istemcinin gönderdiği XFCC silinsin |
| loadgen ve şube terminali token alıp yeniliyor | Her kanal artık token istiyor |
| **Kaynak düzeltmeleri** (bkz. aşağıda): Prometheus agent modu, merkeze yalnızca Istio metrikleri, merkezde 6 saat saklama, apiserver `GOMEMLIMIT`, optimize Keycloak, Kyverno probe toleransı | Keycloak'ı eklerken ortam bellek ve CPU baskısıyla kilitlendi |
| Yol haritasına `09b · consent` | Üçüncü taraf açık bankacılık rızası ayrı bir konu (bu adımda first-party akışlarda consent yok) |

## Eklenen bileşenler

| Bileşen | Amacı | Neden gerekli | Muadilleri | Neden bu seçildi |
|---------|-------|---------------|------------|------------------|
| **Keycloak 26.8** | Kimlik sağlayıcı (OIDC/OAuth2) | Müşteri, partner ve personel kimliği; token üretimi | Red Hat build of Keycloak (RHBK), Microsoft Entra ID, Ping Identity, ForgeRock, Okta, Auth0 | Açık kaynak, OpenShift'te RHBK olarak destekli; realm, client, brute force, OTP ve federasyon (AD/LDAP) tek üründe |
| **Optimize Keycloak image** (`images/keycloak/Dockerfile`) | Yapılandırmanın build'de derlenmesi (`kc.sh build`) | Optimize edilmemiş açılış ~1 dk çok çekirdekli derleme yapıp mgmt'i kilitledi | Resmi image + `start` (optimize edilmemiş), Keycloak Operator | Gerçek ortamdaki doğru yöntem (CI'da build); salt okunur dosya sistemini de mümkün kıldı |
| **auth-service** (Go, stdlib) | Envoy ext_authz: dış token → iç JWT | Kanal kuralları (realm, client, sertifika bağı) ve iç JWT tek yerde | oauth2-proxy, Envoy `jwt_authn` + Lua, Curity Phantom Token, Authorino (Kuadrant), API gateway eklentileri | Kanal ↔ token kuralları özel; Envoy'un `jwt_authn`'ı yeni JWT imzalayamaz. Bağımlılık yok, ~10 MB |
| **Istio ext_authz** (`CUSTOM` AuthorizationPolicy) | Gateway'de harici yetkilendirme | Her istek auth-service'e sorulsun | Envoy filtresi (EnvoyFilter), API gateway | Istio'nun desteklenen yolu; kanal başına sağlayıcı ile `x-auth-channel` istemci tarafından değiştirilemez |
| **Istio RequestAuthentication** (inline JWKS) | Internal'da iç JWT doğrulama | Internal, DMZ dışında üretilmiş kimliğe güvenmesin | Uygulama içinde JWT doğrulama, OPA | Mesh'te, her waypoint'te; uygulamalar imza doğrulamak zorunda kalmaz. Inline JWKS: internal'dan DMZ'ye ağ çağrısı yok |

## Yapılanlar

### Kanal kuralları (auth-service)

| Kanal | Realm (`iss`) | Client (`azp`) | Rol | Ek koşul |
|-------|---------------|----------------|-----|----------|
| web | `customers` | `web-bff` | `customer` | – |
| mobile | `customers` | `mobile-app` | `customer` | – |
| partner | `partners` | = sertifika CN'i (`x-partner-id`) | `partner` | token sertifikaya bağlı (RFC 8705 benzeri) |
| branch | `staff` | `branch-teller` | `teller`, `operations` | cihaz sertifikası (XFCC `Subject`) |

**Kontrol sırası:**
1. `Authorization: Bearer` var mı? Yoksa 401.
2. JWT biçimi ve `alg=RS256`.
3. `iss` = kanalın realm'i. Değilse 403; başka realm'in JWKS'i hiç çekilmez.
4. İmza (Keycloak JWKS, `kid` ile; bilinmeyen `kid`'de en fazla 10 sn'de bir yeniden çekilir).
5. `exp`/`nbf` (30 sn tolerans) ve `typ=Bearer`.
6. `azp`, rol ve kanal koşulu.

Hata kodları: imza, süre ve biçim hataları **401**; yanlış realm, client, rol ya da sertifika **403**.

**İç JWT:**

```json
{ "iss": "auth.dmz.corp.mesh", "aud": "internal-apis", "sub": "<keycloak sub>", "roles": ["customer"],
  "channel": "mobile", "idp": "customers", "azp": "mobile-app", "preferred_username": "ayse",
  "iat": 1793514284, "exp": 1793514584, "jti": "…" }
```

Partner kanalında `partner_id`, şube kanalında `branch_device` eklenir. İç JWT'nin ömrü `min(5 dk, dış token'ın exp'i)`. Aynı token, kanal ve sertifika için üretilen iç JWT önbelleklenir.

### Realm'ler (kod olarak)

| Realm | Client'lar | Güvenlik ayarları |
|-------|-----------|-------------------|
| `customers` | `web-bff`, `mobile-app` (public, PKCE S256) | token 5 dk · oturum 15 dk · brute force (5 deneme) · parola ≥ 12 |
| `partners` | `acme`, `initech` (confidential, client credentials) | token 5 dk · yalnızca service account |
| `staff` | `branch-teller` (public, PKCE) | token 5 dk · oturum 30 dk · brute force (3) · parola ≥ 14 + geçmiş · **OTP** (yeni kullanıcılarda zorunlu kurulum) |

Tüm client'larda `fullScopeAllowed: false` ve scope eşlemeleri var: token yalnızca client'ın rolünü taşıyor (Keycloak'ın varsayılan `offline_access` vb. rolleri yok). Direct grant (ROPC) yalnızca test client'larında ve **yalnızca lab** için açık. Client secret'ları ve test parolaları `05b`'de üretilip realm'e yerleştiriliyor; repoda yok.

### Kaynak sorunu ve çözümleri

Keycloak eklenirken ortam kilitlendi. Zincir şöyle işledi:
1. ~9 saattir çalışan ortamda kullanılabilir bellek ~1 GB'a düşmüştü:
   - Merkezi Prometheus ~0,9 GB'a çıkmıştı.
   - Yerel Prometheus'lar 0,6-1 GB kullanıyordu.
   - kube-apiserver'lar 1,1-1,2 GB'a büyümüştü.
2. Keycloak'ın optimize edilmemiş açılışı mgmt node'una ~1 dk çok çekirdekli yük bindirdi.
3. Kyverno başlangıç kontrolüne 2 dakikada yetişemedi ve yeniden başlatıldı.
4. Webhook **fail-closed** olduğu için o sırada mgmt'te (sonra cluster-a'da da) **hiçbir pod oluşturulamadı**. 05'te kısıt olarak yazdığımız risk böylece canlı olarak gerçekleşti.

| Düzeltme | Etki |
|----------|------|
| dmz ve cluster-a Prometheus'ları **agent modunda** (`--agent`: yerel veritabanı ve kural yok) | 565-964 MB → ~270-310 MB |
| Merkeze yalnızca `istio_*`, `pilot_*`, `up` (`write_relabel_configs`); merkezde saklama 15 gün → **6 saat** | Merkezi Prometheus saatler içinde büyümüyor |
| kube-apiserver'a `GOMEMLIMIT=700MiB` (kind `kubeadmConfigPatches`, `extraEnvs`) | 1,1-1,2 GB → ~720-785 MB |
| Optimize Keycloak image'ı (`kc.sh build` CI'da), `start --optimized` | Açılışta derleme ve CPU patlaması yok; salt okunur dosya sistemi |
| Kyverno başlangıç kontrolü 20×6 sn → 60×6 sn, liveness 2 → 4 deneme | Yük altında kilitlenme döngüsü kırıldı |

Sonuç: node CPU'su %300-700'den %37-47'ye indi. Kullanılabilir bellek Keycloak (~650 MB) eklendiği halde ~3,25 GB, yani 07'deki seviyede.

## Değişen dosyalar

| Dosya | Değişiklik |
|-------|------------|
| `services/auth-service/` | **Yeni.** Go kodu, Dockerfile, go.mod |
| `images/keycloak/Dockerfile` | **Yeni.** Optimize Keycloak build'i |
| `infra/keycloak/realm-{customers,partners,staff}.json` | **Yeni.** Realm tanımları (yer tutucularla) |
| `manifests/mgmt/30-keycloak.yaml`, `35-keycloak-entry.yaml` | **Yeni.** Keycloak; mgmt girişi (yalnızca DMZ egress, yalnızca 3 realm) |
| `manifests/dmz/12-auth-service.yaml`, `27-ext-authz.yaml` | **Yeni.** auth-service + JWKS çıkışı; kanal gateway'lerinde `CUSTOM` politika, SSO'da `/admin` reddi |
| `manifests/cluster-a/45-request-authentication.yaml` | **Yeni.** İç JWT doğrulama (inline JWKS) |
| `istio/values/istiod-dmz.yaml`, `ingress-gateway-branch.yaml` | **Yeni.** ext_authz sağlayıcıları (yalnızca DMZ); şube gateway'inde XFCC |
| `manifests/dmz/20-23-*.yaml`, `30-internal-clusters.yaml` | `Authorization` siliniyor; SSO rotaları; egress `allow-sso-exit` |
| `manifests/cluster-a/15-account-api.yaml`, `30-internal-gateway.yaml`, `40-security.yaml` | `requestPrincipals` zorunlu; account-api'de rol kontrolü |
| `manifests/mgmt/00-namespaces.yaml`, `20-data.yaml` | `iam`; Keycloak veritabanı ve erişimi |
| `services/web-bff`, `services/account-api` | 0.2.0: `x-user-jwt` aktarımı; kullanıcı logu |
| `scripts/03-generate-certs.sh`, `05b-create-data-secrets.sh`, `lib.sh` | İç JWT anahtarı + JWKS; Keycloak ve auth secret'ları; `__INTERNAL_JWKS__` yer tutucusu |
| `scripts/04-install-istio.sh`, `05-install-gateways.sh`, `03b-publish-images.sh` | DMZ istiod değerleri; şube gateway değerleri; `images/` altındaki build'ler |
| `scripts/06b-deploy-edge.sh`, `06c-deploy-branch.sh` | loadgen ve şube terminali token alıyor |
| `scripts/07-install-observability.sh` | Prometheus agent modu, metrik filtresi, merkezde 6 saat |
| `clusters/*.yaml`, `infra/kyverno/values.yaml` | apiserver `GOMEMLIMIT`; Kyverno probe toleransı |
| `scripts/08-verify.sh` | Token yardımcıları; kimlik testleri |
| `docs/tools.md`, `docs/images/src/` | **Yeni.** Araçlar dokümanı; topoloji diyagramı üreteçleri |

## Tasarım kararları

- **Token exchange DMZ'de, internal'da yalnızca iç JWT.** Dış token'ı internal servislere taşımak, onu her servise açmak demek; ayrıca IdP'ye internal'dan bağımlılık getirir. İç JWT'nin anahtarı yalnızca DMZ'de olduğu için internal, kimliğin DMZ'den geçtiğinden emin olabilir.
- **Kanal başına ext_authz sağlayıcısı.** `x-auth-channel` her sağlayıcıda sabit ve gateway tarafından ekleniyor; istemci ezemiyor. Tek sağlayıcı + `x-channel` kullanılsaydı, VirtualService header'ları ext_authz'den sonra uygulandığı için kanal bilgisi henüz yazılmamış olurdu.
- **Partner token'ı sertifikaya bağlı.** Çalınan bir client secret, partnerin sertifikası olmadan işe yaramıyor.
- **Web kanalında şimdilik Bearer token.** BFF'te cookie oturumu (token handler: HttpOnly/Secure/SameSite, CSRF) tarayıcıda login yönlendirmesi gerektiriyor; ayrı bir iş olarak bırakıldı.
- **Direct grant (ROPC) yalnızca lab testleri için.** Gerçek akışlar authorization code + PKCE (web, mobil, şube) ve client credentials (partner).
- **Consent yok:** web, mobil ve şube first-party; partner client credentials ile kendi adına çağırıyor. Üçüncü tarafın müşteri adına erişimi (açık bankacılık) `09b · consent`'te.
- **auth-service fail-closed** (`failOpen: false`): auth-service erişilemezse kanallar kapanır. Gerçekte en az 2 replika.

## STRIDE (yeni akışlar)

| Akış | Tehdit | Senaryo | Kontrol | Durum |
|------|--------|---------|---------|-------|
| Kanal → DMZ | **S**poofing | Token'sız ya da sahte token | ext_authz: imza, iss, exp (test: 401) | ✅ |
| | **T**ampering | Token gövdesi değiştirilir (ör. `sub`) | İmza doğrulaması (test: değiştirilmiş token 401) | ✅ |
| | **E**levation of privilege | Bir kanalın token'ı başka kanalda kullanılır | Kanal ↔ realm/client kuralı (test: mobil token web'de 403, müşteri token'ı şubede 403) | ✅ |
| | **S**poofing | Çalınan partner client secret'ı | Token sertifikaya bağlı (test: acme token'ı + initech sertifikası 403) | ✅ |
| DMZ → internal | **S**poofing | İç JWT sahte üretilir | Anahtar yalnızca DMZ'de; internal imza doğrular (test: anahtar yalnızca dmz'de) | ✅ |
| | **I**nformation disclosure | Dış token internal'a sızar | `Authorization` gateway'de siliniyor (test) | ✅ |
| | **E**levation of privilege | JWT'siz istek internal'a ulaşır | `requestPrincipals` zorunlu (BFF 0.1.0'ın JWT'siz çağrısı 403 aldı) | ✅ |
| | **R**epudiation | Kim ne yaptı bilinmez | İç JWT'de sub, kanal, partner/cihaz; account-api logluyor | ⚠️ merkezi log yok (`10`) |
| IdP | **S**poofing | Parola deneme | Brute force koruması; personelde OTP | ⚠️ müşteride MFA yok |
| | **E**levation of privilege | Yönetim konsoluna internetten erişim | `/admin` ve master realm DMZ'de ve mgmt'te reddediliyor (test: 403) | ✅ |
| | **D**enial of service | auth-service veya Keycloak çöker | Fail-closed; tek replika | ⚠️ |
| | **I**nformation disclosure | Token'da gereğinden fazla rol | `fullScopeAllowed: false` + scope eşlemeleri | ✅ |

## Karşılaşılan sorunlar ve çözümler

| # | Sorun | Neden | Çözüm |
|---|-------|-------|-------|
| 1 | **Ortam kilitlendi:** Keycloak açılmıyor, Kyverno yeniden başlıyor, mgmt'te pod oluşturulamıyor | Bellek baskısı + Keycloak'ın açılış derlemesi + Kyverno fail-closed (bkz. kaynak sorunu) | Prometheus agent ve metrik filtresi, apiserver `GOMEMLIMIT`, optimize Keycloak, Kyverno probe toleransı; ortam sıfırdan kuruldu |
| 2 | auth-service çöküyor: `open /keys/signing.key: permission denied` | Secret dosyası `0400` ve root'a ait; süreç UID 65532 | `fsGroup: 65532` + `defaultMode: 0440` |
| 3 | BFF dashboard `bad_gateway`, internal 403 | Manifest'lerde web-bff/account-api hâlâ 0.1.0; eski BFF `x-user-jwt`'yi iletmiyordu → internal JWT'siz isteği reddetti (zorunluluk çalışıyor) | Manifest'ler 0.2.0'a güncellendi |
| 4 | Keycloak uyarısı: "Full scope allowed" | Token kullanıcının tüm realm rollerini taşıyordu | `fullScopeAllowed: false` + client başına scope eşlemesi |
| 5 | Prometheus agent açılmıyor: `rule_files is not allowed in agent mode` | Istio addon yapılandırmasında kural dosyaları var | Agent modunda `rule_files` bloğu kaldırılıyor |
| 6 | 05b'de Keycloak realm secret'ı oluşturulamıyor | `mktemp`'in `/tmp/...` yolunu Windows kubectl'i çözemiyor | `pwd -W` ile `C:/...` yolu |
| 7 | Istio AuthZ yolu reddedildi (`/realms/*/protocol/...`) | Istio yol ortasında `*` desteklemiyor | `{*}` şablonu |
| 8 | Testler: değiştirilmiş token 403 (401 beklenirken), WAF probe 401 | Test payload'ında `iss` yoktu (önce realm kontrolü); probe token taşımıyordu | Payload gerçek token'dan türetiliyor; probe token taşıyor |

## Doğrulama

Sıfırdan kurulum: `99-destroy.sh` → `setup.sh` (tek seferde, elle müdahale yok). **Süre: 27 dk** (paralel iş yüzünden; normalde ~20 dk). **Sonuç: 131 başarılı, 0 başarısız.** Önceki adımların testleri de token'la geçiyor.

Bu adımda eklenen testler (`08-verify.sh` → "9) Kimlik"):

| Test | Beklenen | Sonuç |
|------|----------|-------|
| Keycloak'tan müşteri, partner ve personel token'ı alınabiliyor | 3 token | ✔ |
| Token'sız istek: web / mobil / partner / şube | 401 | ✔ ✔ ✔ ✔ |
| Değiştirilmiş token (imza tutmuyor) | 401 | ✔ |
| Mobil token'ı web kanalında | 403 | ✔ |
| Müşteri token'ı şube kanalında | 403 | ✔ |
| acme token'ı + initech sertifikası | 403 | ✔ |
| Personel token'ı + cihaz sertifikası: hesaplar | 200 | ✔ |
| İç servise `x-user-jwt` ulaşıyor, `Authorization` ulaşmıyor | – | ✔ ✔ |
| İç JWT: `iss=auth.dmz.corp.mesh`, `aud=internal-apis`, `channel`, ömür ≤ 5 dk | – | ✔ ✔ ✔ ✔ |
| İç JWT (partner): `partner_id=acme`; (şube): `branch_device=sube-0001` | – | ✔ ✔ |
| account-api isteği kullanıcı ve kanalla logluyor | `channel="mobile"` | ✔ |
| Keycloak `/admin` ve master realm internetten | 403 | ✔ ✔ |
| İç JWT imza anahtarı yalnızca DMZ'de | `dmz` | ✔ |
| Pod Security: `auth` (dmz), `iam` (mgmt) | restricted, ihlal yok | ✔ ✔ |

Token içeriği kontrolü: müşteri token'ı yalnızca `customer` rolünü taşıyor (`realm_access.roles: ["customer"]`), ömür 300 sn.

Kaynak kullanımı:

| | 07-data | 08-token-exchange |
|---|---|---|
| mgmt node'u | ~2,8 GB | ~3,1 GB (Keycloak ~650 MB; Prometheus ve apiserver küçüldü) |
| cluster-a / dmz node'u | ~2,5 / ~2,7 GB | ~2,3 / ~2,5 GB |
| kube-apiserver (cluster başına) | ~0,86 GB (saatler içinde 1,2 GB'a) | ~0,72-0,79 GB (`GOMEMLIMIT`) |
| Docker VM'inde kullanılabilir bellek | ~3,0 GB | ~3,25 GB |

## Bilinen kısıtlar

- Web kanalında cookie oturumu ve CSRF yok (Bearer token).
- Müşteri realm'inde MFA ve passkey yok; refresh token rotasyonu yok; step-up (`acr`) yok (`09 · l7-policies`).
- auth-service ve Keycloak tek replika; ext_authz fail-closed.
- Direct grant (ROPC) test client'larında açık (yalnızca lab).
- İç JWT imza anahtarı ve Keycloak realm anahtarları diskte/DB'de; HSM yok (`13 · secrets`: Vault Transit).
- İç JWT anahtar rotasyonu elle (JWKS'e yeni anahtar eklenip eskisi bir süre tutulmalı).
- Kişi bazlı yetki (ör. müşteri yalnızca kendi hesabını görsün, BOLA) yok: `09 · l7-policies`.
- Personel login sayfaları `sso.apps.example.local` adresini kullanıyor; şube ağından yalnızca token uç noktası (direct grant) erişilebilir.
