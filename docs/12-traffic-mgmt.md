# 12 · Trafik yönetimi: canary, zaman aşımı, yeniden deneme, circuit breaker, hata enjeksiyonu

| | |
|---|---|
| **Branch** | `traffic-mgmt` (açıldığı yer: `tracing`) |
| **Durum** | ✅ Tamamlandı (275/275 test) |

## Amaç

Servisler arası trafiği kontrollü yönetmek ve hatalara dayanıklı hale getirmek:
- **Yeni sürüm küçük bir payla devreye girsin (canary).**
- **Yavaş bir servis zincirin tamamını kilitlemesin (zaman aşımı).**
- **Geçici hatalar kullanıcıya yansımasın (yeniden deneme).** Para hareketi ise asla çift yapılmasın.
- **Bozuk bir pod havuzdan çıkarılsın (circuit breaker, outlier detection).**
- **Bunların gerçekten çalıştığı hata enjeksiyonuyla gösterilsin.**

Hedefteki karşılığı GW-16'nın bir kısmı (dayanıklılık) ve INT bölümünün işletim maddeleri.

## Adım sonundaki durum

| Konu | Durum |
|------|-------|
| Canary | account-api **v1** (%90) ve **v2** (%10). Aynı image (0.5.1), farklı dağıtım (`version` etiketi, `RELEASE`); yanıtta `release` alanı. Ağırlıkları account-api'nin waypoint'i uygular |
| Zaman aşımı | account-api: GET 3 sn (deneme başına 1 sn), yazma 5 sn. api-a: GET 5 sn (deneme başına 2 sn); 3 sn'lik yanıt 2 sn'de 504 (test) |
| Yeniden deneme | Yalnızca GET: 2 ek deneme (deneme başına 1–2 sn), bağlantı hatası / 503'te. **POST (transfer, onay) yeniden denenmez** (çift işlem riski) |
| Circuit breaker | Bağlantı havuzu sınırları (account-api: 50 bağlantı, 20 bekleyen istek; aşılırsa hemen 503 `UO`) |
| Outlier detection | Art arda 5 adet 5xx veren pod 15 sn havuzdan çıkarılır (en fazla %50). api-a 2 replika: biri çıkarılınca diğeri hizmet verir |
| Hata enjeksiyonu | Yalnızca test sırasında (`tests/traffic/account-api-fault.yaml`), test User-Agent'ıyla (`lab-fault-delay`, `lab-fault-abort`; DMZ token handler özel header'ları iletmez): 5 sn gecikme, 503. Test sonunda kalıcı kurallar geri yüklenir |
| Gözlem | Access log'a `upstream_attempts` (deneme sayısı) eklendi. Waypoint'lerde outlier / retry / timeout / taşma sayaçları açık (`proxyStatsMatcher`). Kiali'de v1 / v2 ayrı görünür |

## Önceki adıma göre değişenler

| Değişiklik | Neden |
|------------|-------|
| account-api 0.5.1: `RELEASE` → yanıtta `release` | Canary'de hangi sürümün yanıt verdiği görülsün |
| `manifests/cluster-a/15-account-api.yaml`: v1 Deployment seçicisine `version: v1` | v1 Deployment'ı v2 pod'larını sahiplenmesin |
| **Yeni** `17-account-api-v2.yaml` | Canary sürümü |
| **Yeni** `18-traffic-policies.yaml`: DestinationRule ve VirtualService (account-api, api-a) | Ağırlık, zaman aşımı, yeniden deneme, bağlantı havuzu, outlier detection |
| `15-account-api.yaml`, `20-waypoint.yaml`: waypoint pod'una `proxyStatsMatcher` | Istio cluster sayaçlarını varsayılan olarak açmıyor |
| istiod: access log'a `upstream_attempts` | Yeniden denemenin kanıtı logda |
| **Yeni** `tests/traffic/account-api-fault.yaml` | Hata enjeksiyonu yalnızca test sırasında |
| Doğrulama: account-api log kontrolleri iki sürümü de okuyor (`-l app=account-api`); "16) Trafik yönetimi" | İsteklerin %10'u artık v2'de |
| `manifests/dmz/20-public-gateway.yaml`: web rotasında deneme başına süre 4 → 6 sn | Token handler Keycloak'ı 5 sn bekliyor; Keycloak yavaşken gateway isteği önce kesiyordu (logout 504, oturum açık kalıyordu) |

## Tasarım kararları

- **Kurallar hedefin waypoint'inde.** Ambient'te VirtualService ve DestinationRule, hedef servisin waypoint'inde uygulanır. BFF'ler ve gateway'ler değişmedi.
- **Yeniden deneme yalnızca okumada.** Transferde zaman aşımından sonra yeniden deneme, işlemin iki kez yapılmasına yol açabilir. Yazma işlemlerinde idempotency anahtarı olmadan yeniden deneme yok (test).
- **Retry ≠ 500.** Yalnızca geçici olduğu varsayılan durumlar yeniden denenir: bağlantı hatası, akış reddi, 503. Uygulamanın kendi 500'ü tekrarlanmaz; aynı hatayı üç kez almanın faydası yok, yükü üçe katlar.
- **Zaman aşımı zincir boyunca azalan.** Kullanıcıya en yakın katmanın süresi en uzun olmalı (gateway > BFF > domain). Burada domain servislerinde 3–5 sn.
- **Canary başlıkla zorlanmıyor.** Başlıkla v2'ye yönlendirme dışarıdan kötüye kullanılabilirdi (kanal kotalarının dışında yük, test sürümüne erişim). Gerçekte canary hedefi kimlikle (ör. personel ya da iç test kullanıcıları) ya da Argo Rollouts ile otomatik analizle seçilir (16 · gitops).
- **Hata enjeksiyonu kalıcı değil.** Başlıkla tetiklenen bir hata kuralı üretimde kalırsa saldırı yüzeyi olur; yalnızca test süresince uygulanıyor.

## STRIDE (yeni ve değişen akışlar)

| Akış | Tehdit | Senaryo | Kontrol | Durum |
|------|--------|---------|---------|-------|
| Yeniden deneme | **T**ampering | Zaman aşımına uğrayan transfer tekrar gönderilir, para iki kez çıkar | POST yeniden denenmez (test) | ✅ |
| | **D**enial of service | Yeniden denemeler yükü katlar (retry storm) | Yalnızca GET, en fazla 2, yalnızca geçici hatalar; 500 tekrarlanmaz | ✅ |
| Bağımlılık | **D**enial of service | Yavaş servis zinciri kilitler | Zaman aşımı (test: yavaş yanıt → 504), bağlantı havuzu sınırı | ✅ |
| | **D**enial of service | Bozuk pod hata döndürmeye devam eder | Outlier detection (test) | ✅ |
| Canary | **E**levation of privilege | Dışarıdan test sürümüne yönlenmek | Başlıkla yönlendirme yok; yalnızca ağırlık | ✅ |
| Hata enjeksiyonu | **D**enial of service | Başlıkla tetiklenen hata kuralı kalıcı olur | Yalnızca test sırasında; sonra geri yüklenir (test) | ✅ |

## Karşılaşılan sorunlar ve çözümler

| # | Sorun | Neden | Çözüm |
|---|-------|-------|-------|
| 1 | Waypoint'te retry / outlier sayaçları yoktu | Istio varsayılan olarak yalnızca sınırlı istatistik açıyor | Waypoint pod'larına `proxyStatsMatcher` (yalnızca gereken sayaçlar) |
| 2 | Testler transfer / onay logunu bulamayabilirdi | İsteklerin %10'u v2'de; testler yalnızca v1'in logunu okuyordu | `kubectl logs -l app=account-api` |
| 3 | v1 Deployment'ın seçicisi değişince güncelleme reddedilir | Seçici değiştirilemez (immutable) | Çalışan ortamda Deployment silinip yeniden oluşturuldu; sıfırdan kurulumda sorun yok |
| 4 | Hata enjeksiyonu testi tetiklenmedi (200) | Test header'ı (`x-fault-test`) internal'a ulaşmıyor: DMZ token handler yalnızca izinli header'ları iletir (tasarım gereği) | Test kuralı izinli bir header'a, User-Agent'a bağlandı |
| 5 | Enjekte 5 sn gecikme 2 sn'lik zaman aşımına takılmadı (200) | Envoy gecikmeyi router'dan önce uygular; enjekte gecikme rotanın zaman aşımına sayılmaz. Önceki denemede görülen 504 DMZ gateway'inin 4 sn'lik sınırındandı | Zaman aşımı gerçek yavaş yanıtla sınanıyor (api-a, podinfo `/delay/3` → 2 sn'de 504); gecikme testi yalnızca gecikmenin uygulandığını sınıyor |
| 6 | Kural uygulandıktan / kaldırıldıktan sonra test eski kuralı gördü | Yük altında waypoint'e yayılma 8 sn'den uzun sürebiliyor | Test kural etkin olana (abort → 503) ve kalkana (200) kadar bekliyor, en fazla 60 sn |
| 7 | Web logout 504, aynı cookie geçerli kaldı | DMZ web rotasında deneme başına 4 sn; token handler Keycloak logout'unu 5 sn bekliyor. Keycloak yükte yavaşlayınca gateway önce kesti, oturum silinmedi | Deneme başına süre 6 sn (handler'ın kendi zaman aşımı içeride kalır; oturum her durumda silinir) |
| 8 | Yük altında tek tük kanal hataları (şube transferi 404 yerine 403, mobil transfer 401) | mgmt CPU'su doyunca Keycloak introspection / exchange zaman aşımına uğruyor; auth-service 503 döner, Envoy ext_authz bunu 403'e çevirir (`status_on_error` varsayılanı) | Kod hatası değil: aynı istek tek başına doğru sonucu veriyor. Kısıtlara eklendi |

## Doğrulama

Sıfırdan kurulum (`99-destroy.sh` → `setup.sh`), ardından `08-verify.sh`: **275 başarılı, 0 başarısız.** Sıfırdan kurulumdaki ilk doğrulamada 2 kontrol kaldı (sorun 5 ve 8). Test düzeltmesinden sonra aynı ortamda doğrulama yeniden çalıştırıldı; bu arada yalnızca test script'i ve test YAML'ı değişti.

Bu adımda eklenen testler (`08-verify.sh` → "16) Trafik yönetimi"):

| Test | Beklenen | Sonuç |
|------|----------|-------|
| v1 ve v2 çalışıyor | `v1 v2` | ✅ |
| 60 istekte v2 payı (1–15) | ~%10 | ✅ (v1=54, v2=6) |
| Transfer (POST) yeniden denenmiyor (yapılandırma) | 0 | ✅ |
| GET 503: 3 deneme; POST 503: 1 deneme (access log) | – | ✅ |
| Outlier detection: pod havuzdan çıkarıldı; api-a hizmet vermeye devam ediyor | – | ✅ (ejection 1 → 2; 200) |
| Zaman aşımı: 3 sn'lik yanıt ~2 sn'de 504 (api-a, podinfo `/delay/3`) | 504 | ✅ (504, 2249 ms) |
| Enjekte hata → 503; enjekte gecikme uygulanıyor (5 sn, 200); kaldırılınca 200 | – | ✅ (503; 5269 ms, 200; 200) |
| account-api v2 imzalı image | digest | ✅ |

## Bilinen kısıtlar

- **Canary elle.** Ağırlık manifestte; metriklere bakıp otomatik ilerleme / geri alma yok (Argo Rollouts, `16 · gitops`).
- **İdempotency yok.** Transfer yeniden denenmiyor ama istemci tekrar gönderirse tekrar işlenir; gerçekte `Idempotency-Key` başlığı ve sunucu tarafı kayıt gerekir. Lab'de transfer işlem yapmıyor (INT-09).
- **Zaman aşımı bütçesi elle.** Domain servislerinde 2–5 sn, DMZ kanal rotalarında 10 sn (web: deneme başına 6 sn); uçtan uca zaman aşımı bütçesi (deadline propagation) yok.
- **ext_authz hata durumu 403.** IdP yavaşken auth-service'in 503'ü istemciye 403 olarak gider; istemci bunu kalıcı ret sanar. Gerçekte ext_authz sağlayıcısında `statusOnError: 503` (tekrar denenebilir) düşünülmeli.
- **Outlier detection tek replikalı servislerde** (account-api v1 / v2 birer pod) havuzu boşaltabilir; en fazla %50 sınırı tek pod'da yine de o pod'u çıkarır (Envoy en az bir host'u çıkarır).
- **Fault injection yalnızca account-api'de** tanımlı; kaos deneyleri (pod öldürme, ağ bölünmesi) yok.
