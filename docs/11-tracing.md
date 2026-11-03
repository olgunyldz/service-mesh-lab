# 11 · Dağıtık iz: Tempo, Envoy (OpenTelemetry), log ↔ iz

| | |
|---|---|
| **Branch** | `tracing` (açıldığı yer: `admin-access`) |
| **Durum** | ✅ Tamamlandı, sıfırdan kurulumla doğrulandı (263/263 test) |

## Amaç

Bir isteğin zone'lar arasındaki yolculuğunu tek bir iz olarak görmek. İstek DMZ gateway'inden token handler'a, internal ingress'ten BFF'e ve domain servisine kadar gidiyor; her hop'un süresi ve sonucu iz üzerinde görünmeli. Loglardan ize, izden loglara tek tıkla geçilebilmeli. Hedef: AC-10 (bir isteğin uçtan uca izlenmesi), SOC-03 (ortak korelasyon kimliği).

## Adım sonundaki durum

| Konu | Durum |
|------|-------|
| Tempo 2.10.8 | mgmt `logging`, tek binary, yerel disk (PVC), 24 saat. OTLP/HTTP (4318) alır. ~100 MB bellek, boştayken ~%2 CPU |
| İz kaynakları | Tüm gateway'lerin ve waypoint'lerin Envoy'ları (Istio Telemetry API, sağlayıcı `otel`). ztunnel L4 olduğu için iz üretmez |
| Örnekleme | İsteklerin **%10**'u (`randomSamplingPercentage`). `x-client-trace-id` başlıklı istek her zaman izlenir (Envoy). Karar W3C `traceparent` ile tüm hop'lara taşınır |
| Taşıma | Her cluster'da aynı ad: Envoy → `traces-mgmt.istio-egress:80` (kendi egress gateway'i) → dmz / cluster-a: mTLS ile mgmt girişi (`traces.mgmt.internal`) → Tempo; mgmt: doğrudan Tempo. Yalnızca `POST /v1/traces` |
| Geri besleme koruması | Egress gateway'ler ve mgmt ingress gateway span üretmez (`disableSpanReporting`). Log, metrik ve iz gönderimini izleyip yeniden gönderirlerdi. Gönderim trafiği access log'a da yazılmaz |
| Log ↔ iz | Access log'a `trace_id` ve `traceparent` eklendi. Başarılı isteklerin access log'u **yalnızca izi örneklendiyse** tutulur: tutulan her başarılı logun Tempo'da izi var ve tersi. Hatalar, redler ve `x-log-force` her zaman tutulur |
| Grafana | Tempo veri kaynağı yalnızca **Main Org** (yönetici) ve **Network** organizasyonunda; izler tüm kategorileri kestiği için diğer ekiplere açık değil. Loki'deki `trace_id` → Tempo'da iz (derived field); Tempo'daki iz → ilgili loglar (`tracesToLogsV2`); node graph açık |

### Örnek iz (web, zorunlu izleme)

```
dmz-ingressgateway.istio-ingress        (dmz, web gateway)
└─ waypoint.edge-web                    (dmz, web token handler)
   └─ istio-ingressgateway.istio-ingress (cluster-a, internal giriş)
      └─ waypoint.channel-bff           (web-bff)
         └─ waypoint.api-a              (domain servisi)
```

`dmz-egressgateway` bu izde yok: span üretmiyor, ama `traceparent`'ı olduğu gibi geçirdiği için iz kopmuyor.

## Önceki adıma göre değişenler

| Değişiklik | Neden |
|------------|-------|
| `infra/tracing/tempo.yaml` (07b uygular) | İz deposu |
| istiod: `extensionProviders` → `otel` (OTLP/HTTP, `traces-mgmt.istio-egress:80`); `istiod-dmz.yaml`'da da (helm listeleri birleştirmez) | Envoy'ların izi nereye göndereceği |
| `62-access-log-filter.yaml` (Telemetry `mesh-default`): `tracing` %10; iz gönderimi access log'dan da hariç | Mesh geneli örnekleme |
| `63-traces-exit.yaml` (dmz, cluster-a, mgmt): `traces-mgmt` Service, DestinationRule (`DISABLE`: gönderen Envoy'lar mesh'te, egress'in dinleyicisi düz HTTP), Gateway, VirtualService, AuthorizationPolicy, Telemetry `no-spans` | Log çıkışıyla aynı desen; geri besleme koruması |
| `manifests/mgmt/52-traces-entry.yaml` | mgmt girişi (yalnızca egress gateway kimlikleri, yalnızca `POST /v1/traces`); mgmt ingress span üretmez |
| Access log: `trace_id`, `traceparent` | Log ↔ iz |
| Fluent Bit: başarılı access log örneklemesi `traceparent`'ın örnekleme bayrağına göre (önce `request_id` özetine göreydi) | Log ve iz aynı istekleri tutsun |
| 07b: Tempo, Tempo veri kaynağı (Main Org, Network), Loki'ye `TraceID` bağlantısı | Grafana'da geçişler |
| `LAB_PULLS`: `grafana/tempo:2.10.8` | – |
| Doğrulama: "15) Dağıtık iz" | – |

## Eklenen bileşenler

| Bileşen | Amacı | Neden gerekli | Muadilleri | Neden bu seçildi |
|---------|-------|---------------|------------|------------------|
| **Tempo** | İz deposu | AC-10: isteğin hop hop yolculuğu ve süreleri | Jaeger, Zipkin, Elastic APM, ticari APM'ler | Grafana ve Loki ile doğal geçiş; yalnızca nesne / disk depolaması, düşük kaynak. Sürüm 2.10: 3.x yeni yazma mimarisine geçti (kırıcı değişiklikler), 2.10 serisi bakım görüyor |
| **Envoy OpenTelemetry tracer** (Istio Telemetry API) | Gateway ve waypoint'lerin span üretmesi | Uygulamaya dokunmadan her hop'un izi | OpenTelemetry SDK ile uygulama içi iz, OTel Collector | Mesh zaten her hop'ta; Go servisleri `traceparent`'ı ters proxy ile aynen taşıyor |

## Tasarım kararları

- **İz mesh'ten, uygulamadan değil.** Span'leri gateway ve waypoint'ler üretir. BFF'ler ve domain servisleri `traceparent`'ı taşır ama kendi span'lerini üretmez. Servis içi süre, iki waypoint span'i arasındaki farktan okunur. Uygulama içi ayrıntı (DB sorgusu, Keycloak çağrısı) gerekiyorsa OTel SDK eklenir.
- **Örnekleme %10, zorla izleme başlıkla.** CPU bütçesi (10'daki ölçüm). Hata ayıklama ve testler için `x-client-trace-id`; bu Envoy'un standart davranışı.
- **Log ile iz aynı kararı paylaşır.** Örnekleme `traceparent`'ın bayrağına bağlı. Başarılı bir isteğin logu varsa izi de var; logdan ize geçişte boş iz çıkmaz.
- **Geri besleme yok.** Gönderim yolundaki gateway'ler span üretmez; gönderim trafiği access log'a yazılmaz. 10'da yaşanan döngü izlerde tekrarlanmasın.
- **Erişim:** İz, kategoriler arası tam yolu (kanal, BFF, servis, adresler) gösterir. Bu yüzden yalnızca yönetici ve Network ekibi görür; SOC, DBA, uygulama ekipleri görmez (test).

## STRIDE (yeni ve değişen akışlar)

| Akış | Tehdit | Senaryo | Kontrol | Durum |
|------|--------|---------|---------|-------|
| Envoy → Tempo | **S**poofing | Sahte kaynak iz yazar | Zone'lar arası yalnızca egress gateway kimlikleri; mgmt'te yalnızca `POST /v1/traces` | ✅ |
| | **I**nformation disclosure | DMZ'den izler okunur | Sorgu uçları dışarıya kapalı (test: 403) | ✅ |
| İz içeriği | **I**nformation disclosure | İzde token / kişisel veri | Envoy span'leri başlık değeri taşımaz (yöntem, yol, kod, süre, servis) | ✅ |
| | **I**nformation disclosure | Bir ekip tüm sistemin akışını görür | Tempo yalnızca yönetici ve Network (test: soc01 erişemiyor) | ✅ |
| | **T**ampering | İstemci `x-client-trace-id` ile her isteğini izletir | Yalnızca kendi isteklerini; kanal kotalarıyla sınırlı | ⚠️ kabul |
| İz altyapısı | **D**enial of service | İz hacmi makineyi doyurur | %10 örnekleme; gönderim yolu span üretmez (test); Tempo 512 MB sınır | ✅ |

## Karşılaşılan sorunlar ve çözümler

| # | Sorun | Neden | Çözüm |
|---|-------|-------|-------|
| 1 | İzlenen isteğin access log'u Loki'de yoktu | Log örneklemesi (request_id özeti) ile iz örneklemesi bağımsızdı | Log örneklemesi `traceparent`'ın bayrağına bağlandı |
| 2 | Access log'ların yarısında `trace_id` vardı, oysa örnekleme %10 | Envoy izlenmeyen isteğe de iz kimliği verip taşıyor (W3C, sampled=0) | Ölçüt `trace_id`'nin varlığı değil, `traceparent`'ın son baytı (`01`) |
| 3 | Makine gece yine uykuya geçti | Modern Standby | Ortam sabah toparlandı; kodla ilgisi yok |

## Doğrulama

Sıfırdan kurulum: `99-destroy.sh` → `setup.sh` (içinde `08-verify.sh`), tek seferde, elle müdahale yok. **Süre: ~40 dk.** **Sonuç: 263 başarılı, 0 başarısız.**
- 250'den 263'e: 13 yeni test ("15) Dağıtık iz"). Önceki adımların testleri değişmeden geçiyor; log örneklemesinin izle hizalanması 13. bölümü etkilemedi.
- Kurulumdan önce çalışan ortama da uygulandı (263/263).

Kaynak kullanımı (doğrulamadan hemen sonra, node başına): mgmt ~3,4 GB (10'dan +0,1 GB: Tempo), cluster-a ~2,4 GB, dmz ~2,6 GB.

Bu adımda eklenen testler (`08-verify.sh` → "15) Dağıtık iz"):

| Test | Beklenen | Sonuç |
|------|----------|-------|
| Tempo hazır | – | ✔ |
| Zorunlu izlenen web isteği: `traceparent` uygulamaya ulaşıyor ve örneklenmiş | `-01` | ✔ |
| İz Tempo'da: DMZ hop'ları (web gateway, token handler) ve internal hop'lar (ingress, web-bff, api-a) | – | ✔ ✔ |
| Aynı `trace_id` DMZ ve cluster-a access log'larında | 2 | ✔ |
| Grafana: Loki → Tempo ve Tempo → Loki bağlantıları | – | ✔ ✔ |
| Egress gateway'ler span üretmiyor | 0 | ✔ |
| netops01 izleri görüyor, soc01 göremiyor | – | ✔ ✔ |
| DMZ'den sorgu 403, iz gönderimi 200; Tempo imzalı image | – | ✔ ✔ ✔ |

## Bilinen kısıtlar

- **Uygulama içi span yok.** Servis içi adımlar (DB sorgusu, Keycloak'a introspection / exchange) ayrı span değil. auth-service'in Keycloak çağrıları kendi izlerinde.
- **ext_authz (auth-service) hop'u** ilgili gateway'in span'i içinde. Ayrı bir span olarak görünmesi için auth-service'te OTel SDK gerekir.
- **Egress gateway'ler ve mgmt ingress izde yok** (geri besleme koruması). Zone geçişi süresi, iki taraftaki span'lerin farkından okunur.
- **Edge (HAProxy, WAF) izde yok.** İz DMZ gateway'inde başlıyor; gerçekte F5 de `traceparent` üretip iletir.
- **Tek replika, 24 saat, yerel disk.** Gerçekte nesne deposuyla dağıtık Tempo.
- **Tempo'da çok tenant yok.** Erişim Grafana organizasyonlarıyla sınırlı; mgmt içinden Tempo'ya doğrudan erişilebilir (Loki ve Prometheus gibi).
