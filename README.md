# Service Mesh Lab: OpenShift Benzeri Çoklu Cluster Ortamı

Bu proje, kurumsal bir OpenShift yapısını yerelde **kind** ile simüle eder:

- **DMZ cluster**: dış dünyaya açık tek katman. Edge load balancer ve public Istio ingress gateway burada çalışır.
- **cluster-a** ve **cluster-b**: internal cluster'lar. API'ler burada çalışır, dışarıdan doğrudan erişilemez.
- **Istio Ambient Mesh**: sidecar yoktur. L4 mTLS'i **ztunnel**, L7 politikaları **waypoint** üstlenir. Giriş trafiği **ingress gateway**, çıkış trafiği **egress gateway** üzerinden geçer.

> **Adım adım geçmiş:** Her yol haritası maddesinin ayrıntılı dokümanı (yapılanlar, değişen dosyalar, sorunlar, doğrulama) [docs/](docs/README.md) altındadır.

## Mevcut durum

Ortam kuruldu ve aşağıdaki akışların hepsi uçtan uca doğrulandı (`scripts/08-verify.sh`):

| # | Akış | Sonuç |
|---|------|-------|
| 1 | İnternet → DMZ → cluster-a → api-a | ✅ |
| 2 | İnternet → DMZ → cluster-b → api-b | ✅ |
| 3 | api-a → cluster-a egress → cluster-b → api-b (cluster'lar arası) | ✅ |
| 4 | api-a → egress gateway → httpbin.org (internete çıkış) | ✅ |
| – | Mesh dışından internal gateway'e doğrudan erişim | ✅ reddediliyor (istemci sertifikası yok; `00-setup` adımında test edildi) |
| – | Kiali (20001-20003) ve Grafana (3001-3003) erişimi, Kiali graph'larının dolu gelmesi | ✅ (bkz. [Gözlemlenebilirlik](#gözlemlenebilirlik-kiali-prometheus-grafana)) |

Son doğrulama: `01-kiali` adımının sıfırdan kurulumu ([docs/01-kiali.md](docs/01-kiali.md#doğrulama)).

Kullanılan sürümler:

| Bileşen | Sürüm | Not |
|---------|-------|-----|
| kind / Kubernetes | 0.33.0 / v1.36.4 | Her cluster 1 control-plane + 1 worker |
| Istio (kontrol düzlemi) | 1.30.7 | 1.31 GA chart'ları helm reposunda yok. Image'lar `docker.io/istio`'dan (registry önbelleği uyumu) |
| istioctl | 1.31.3 | n-1 kontrol düzlemi desteği |
| Istio dataplane modu | ambient + **native nftables** | WSL2 kernel'inde iptables CONNMARK yok |
| Gateway API CRD | v1.6.0 | |
| MetalLB | v0.16.1 | L2 modu |
| Edge LB | HAProxy 3.0 | |
| Uygulama | podinfo 6.7.1 | |
| Kiali | 2.26.0 | Istio 1.30 addon'undaki sürüm |
| Prometheus / Grafana | Istio 1.30 `samples/addons` | |
| Registry önbelleği | `registry:2.8.3` | docker.io, quay.io, ghcr.io için pull-through cache (bkz. [Registry önbelleği](#registry-önbelleği)) |

---

## Mimari

> Diyagramlar Mermaid ile yazıldı. GitHub doğrudan gösterir; VS Code önizlemesi için
> "Markdown Preview Mermaid Support" eklentisi gerekir.

### Fiziksel yapı

Üç kind cluster'ı da Docker Desktop (WSL2) üzerinde, aynı `kind` docker ağında birer container olarak çalışır. Host'a yalnızca DMZ'nin portu açıktır.

```mermaid
flowchart LR
    host["💻 Windows host<br/>localhost:8080 / 8443"]

    subgraph docker["Docker Desktop · WSL2 · docker ağı kind 172.18.0.0/16"]
        direction LR
        subgraph dmz["kind-dmz · pod 10.10/16 · svc 10.110/16"]
            dmzcp["dmz-control-plane<br/>hostPort 8080→30080<br/>hostPort 8443→30443"]
            dmzw["dmz-worker<br/>node-role=infra"]
        end
        subgraph ca["kind-cluster-a · pod 10.20/16 · svc 10.120/16"]
            cacp["cluster-a-control-plane"]
            caw["cluster-a-worker<br/>node-role=worker"]
        end
        subgraph cb["kind-cluster-b · pod 10.30/16 · svc 10.130/16"]
            cbcp["cluster-b-control-plane"]
            cbw["cluster-b-worker<br/>node-role=worker"]
        end
        lbd(["MetalLB VIP<br/>172.18.200.10"])
        lba(["MetalLB VIP<br/>172.18.201.10"])
        lbb(["MetalLB VIP<br/>172.18.202.10"])
    end

    host -->|"port mapping"| dmzcp
    lbd -.- dmz
    lba -.- ca
    lbb -.- cb
```

Her cluster'da `istio-system` altında aynı Istio bileşenleri çalışır:

```mermaid
flowchart LR
    subgraph node["Her node"]
        cni["istio-cni<br/>DaemonSet<br/>nftables kuralları"]
        zt["ztunnel<br/>DaemonSet<br/>L4 mTLS · HBONE"]
    end
    istiod["istiod<br/>xDS + CA<br/>intermediate CA: cacerts"]
    istiod -->|"xDS config"| zt
    istiod -->|"workload sertifikaları"| zt
    cni -->|"pod trafiğini yönlendirir"| zt
```

### Mantıksal yapı

```mermaid
flowchart TB
    user(["👤 Kullanıcı"])
    internet(["🌐 httpbin.org"])

    subgraph DMZ["DMZ · kind-dmz"]
        direction TB
        haproxy["edge-lb<br/>HAProxy x2 · mesh dışı"]
        dmzgw["dmz-ingressgateway<br/>LB 172.18.200.10<br/>Gateway public-gateway"]
        haproxy -->|"HTTP :80"| dmzgw
    end

    subgraph A["cluster-a · kind-cluster-a"]
        direction TB
        agw["istio-ingressgateway<br/>LB 172.18.201.10<br/>AuthZ: dmz-ingressgateway"]
        subgraph nsa["ns api-a · ambient"]
            awp["waypoint<br/>L7 AuthZ + routing"]
            aapi["api-a x2<br/>podinfo :9898"]
        end
        aeg["istio-egressgateway<br/>ns istio-egress"]
        agw -->|"HBONE"| awp
        awp <-->|"HBONE · ztunnel"| aapi
        awp -->|"mTLS :443"| aeg
    end

    subgraph B["cluster-b · kind-cluster-b"]
        direction TB
        bgw["istio-ingressgateway<br/>LB 172.18.202.10<br/>AuthZ: dmz + egressgateway"]
        subgraph nsb["ns api-b · ambient"]
            bwp["waypoint<br/>L7 AuthZ + routing"]
            bapi["api-b x2<br/>podinfo :9898"]
        end
        beg["istio-egressgateway<br/>ns istio-egress"]
        bgw -->|"HBONE"| bwp
        bwp <-->|"HBONE · ztunnel"| bapi
        bwp -->|"mTLS :443"| beg
    end

    user -->|"HTTP localhost:8080"| haproxy
    dmzgw ==>|"mTLS :443<br/>SNI api-a.apps.example.local"| agw
    dmzgw ==>|"mTLS :443<br/>SNI api-b.apps.example.local"| bgw
    aeg ==>|"mTLS :443<br/>SNI api-b.apps.example.local"| bgw
    aeg -->|"HTTP :80"| internet
    beg -->|"HTTP :80"| internet

    classDef gw fill:#dbeafe,stroke:#2563eb,color:#1e3a8a
    classDef app fill:#dcfce7,stroke:#16a34a,color:#14532d
    classDef edge fill:#fef3c7,stroke:#d97706,color:#78350f
    classDef ext fill:#f3f4f6,stroke:#6b7280,color:#111827
    class dmzgw,agw,bgw,aeg,beg gw
    class awp,bwp,aapi,bapi app
    class haproxy edge
    class user,internet ext
```

Kalın oklar (`==>`) cluster'lar arası mTLS bağlantılarıdır. Cluster'lar birbirine yalnızca bu oklar üzerinden, LoadBalancer IP'leri aracılığıyla ulaşır.

### Ambient veri düzlemi nasıl çalışıyor?

- **istio-cni** (DaemonSet): `istio.io/dataplane-mode: ambient` etiketli namespace'lerdeki pod'ların ağ namespace'ine nftables kuralları yazar. Pod'un giren ve çıkan trafiği aynı node'daki ztunnel'e yönlendirilir. Uygulama container'ına hiçbir şey eklenmez; sidecar yoktur.
- **ztunnel** (DaemonSet, node başına bir tane): L4 proxy'dir. Pod'lar arası trafiği **HBONE** ile taşır (mTLS içinde HTTP CONNECT tüneli, port 15008). Her pod'un kimliği SPIFFE sertifikasıyla temsil edilir: `spiffe://corp.mesh/ns/<ns>/sa/<sa>`.
- **waypoint** (namespace başına bir Envoy deployment'ı): L7 proxy'dir. `istio.io/use-waypoint: waypoint` etiketi olan namespace'lerin ve ServiceEntry'lerin trafiği ztunnel'den waypoint'e gider. HTTP bazlı AuthorizationPolicy, VirtualService yönlendirmesi ve retry/timeout gibi kurallar burada uygulanır.
- **Gateway'ler** (ingress/egress): ambient'e dahil değildir, kendi Envoy'larıyla çalışırlar. Mesh içine HBONE ile, cluster dışına ise `ISTIO_MUTUAL` (Istio sertifikalarıyla mTLS) veya düz HTTP ile bağlanırlar.

### Tasarım kararları

- **Cluster'lar arasında düz ağ yok.** Her cluster kendi bağımsız ambient mesh'ini çalıştırır. Cluster'lar birbirine yalnızca gateway'ler üzerinden, LoadBalancer IP'leri aracılığıyla bağlanır; tıpkı DMZ ile internal zone arasında firewall bulunan gerçek yapılarda olduğu gibi. Bir cluster diğerinin pod IP'lerini veya servislerini bilmez.
- **Ortak güven zinciri.** Tek bir root CA vardır ve her cluster'ın istiod'u kendi intermediate CA'sıyla sertifika üretir (`istio-system/cacerts`, `scripts/03-generate-certs.sh`). Gateway'ler arasındaki `ISTIO_MUTUAL` bağlantısı bu ortak root sayesinde iki taraflı doğrulanır.
- **Ortak trust domain: `corp.mesh`.** Kimlikler servis hesabı (SA) adlarıyla ayrışır: DMZ'deki gateway `dmz-ingressgateway`, internal gateway'ler ise `istio-ingressgateway` adını taşır. AuthorizationPolicy'ler bu adlara göre yazılır.
- **Gateway kurulumu:** ingress ve egress gateway'ler `istio/gateway` Helm chart'ı ve klasik `Gateway` / `VirtualService` API'si ile, waypoint'ler ise Kubernetes Gateway API (`gatewayClassName: istio-waypoint`) ile kurulur.
- **OpenShift benzerlikleri:** `*.apps.example.local` route domain'i, `restricted` Pod Security, sayısal UID ile non-root container'lar, infra/worker node etiketleri ve HAProxy tabanlı edge router.

---

## Trafik akışları (adım adım)

### Akış 1: İnternet → api-a (north-south)

```mermaid
sequenceDiagram
    autonumber
    actor U as Kullanıcı
    box rgb(254,243,199) DMZ cluster
        participant H as HAProxy<br/>edge-lb
        participant D as dmz-ingressgateway
    end
    box rgb(219,234,254) cluster-a
        participant G as istio-ingressgateway
        participant W as waypoint<br/>ns api-a
        participant Z as ztunnel
        participant P as api-a pod
    end

    U->>H: GET / · Host api-a.apps.example.local · localhost:8080
    H->>D: HTTP :80
    Note over D: Gateway public-gateway<br/>VirtualService api-a
    D->>G: mTLS ISTIO_MUTUAL → 172.18.201.10:443
    Note over G: AuthZ allow-only-dmz<br/>kaynak = dmz-ingressgateway mi?
    G->>W: HBONE :15008
    Note over W: AuthZ api-a-allow-ingress<br/>kaynak = istio-ingressgateway, GET/POST
    W->>Z: HBONE :15008
    Z->>P: HTTP :9898
    P-->>U: 200 OK · api-a @ cluster-a
```

| Adım | Nereden → Nereye | Port / Protokol | Şifreleme | Tanımlayan kaynak |
|------|------------------|-----------------|-----------|-------------------|
| 1 | Windows host → dmz node | `localhost:8080` → `30080` | Yok | [clusters/dmz.yaml](clusters/dmz.yaml) `extraPortMappings` |
| 2 | NodePort → HAProxy pod | `30080` → `:8080` HTTP | Yok | [manifests/dmz/10-edge-lb.yaml](manifests/dmz/10-edge-lb.yaml) Service `edge-lb` |
| 3 | HAProxy → dmz-ingressgateway | `:80` HTTP, `X-Forwarded-Proto` eklenir | Yok (DMZ içi) | HAProxy `backend istio_ingress_http` |
| 4 | dmz-ingressgateway: Host eşleşmesi | `api-a.apps.example.local` | – | [manifests/dmz/20-public-gateway.yaml](manifests/dmz/20-public-gateway.yaml) `Gateway public-gateway` + `VirtualService api-a` (timeout 10s, 2 retry) |
| 5 | dmz-ingressgateway → cluster-a ingress gw | `172.18.201.10:443` | **mTLS** (`ISTIO_MUTUAL`, SNI `api-a.apps.example.local`) | [manifests/dmz/30-internal-clusters.yaml](manifests/dmz/30-internal-clusters.yaml) `ServiceEntry` + `DestinationRule cluster-a-gateway` |
| 6 | cluster-a ingress gw: kimlik kontrolü | istemci sertifikası `corp.mesh/ns/istio-ingress/sa/dmz-ingressgateway` olmalı | – | [manifests/cluster-a/30-internal-gateway.yaml](manifests/cluster-a/30-internal-gateway.yaml) `AuthorizationPolicy allow-only-dmz` |
| 7 | cluster-a ingress gw → waypoint | HBONE `:15008` | **mTLS** | `Service api-a` üzerindeki `istio.io/ingress-use-waypoint: "true"` etiketi |
| 8 | waypoint: L7 yetki kontrolü | kaynak `istio-ingressgateway`, metot `GET`/`POST` olmalı | – | [manifests/cluster-a/40-security.yaml](manifests/cluster-a/40-security.yaml) `AuthorizationPolicy api-a-allow-ingress` |
| 9 | waypoint → hedef node'daki ztunnel | HBONE `:15008` | **mTLS** | [manifests/cluster-a/20-waypoint.yaml](manifests/cluster-a/20-waypoint.yaml) |
| 10 | ztunnel → api-a pod | `:9898` HTTP (pod ağ namespace'i içinde) | – | [manifests/cluster-a/10-api-a.yaml](manifests/cluster-a/10-api-a.yaml) |

**Akış 2 (İnternet → api-b)** aynı yolu izler. Farklar: Host `api-b.apps.example.local`, hedef `172.18.202.10:443` ve kaynaklar `manifests/cluster-b/` altında.

### Akış 3: api-a → api-b (cluster'lar arası, egress gateway üzerinden)

Tetikleyici: `POST /api/echo` isteği api-a'ya gelir. podinfo bu isteği `--backend-url=http://api-b.apps.example.local/echo` adresine iletir.

```mermaid
sequenceDiagram
    autonumber
    box rgb(219,234,254) cluster-a
        participant A as api-a pod
        participant ZA as ztunnel
        participant WA as waypoint<br/>ns api-a
        participant E as istio-egressgateway
    end
    box rgb(220,252,231) cluster-b
        participant G as istio-ingressgateway
        participant WB as waypoint<br/>ns api-b
        participant B as api-b pod
    end

    A->>ZA: POST http://api-b.apps.example.local/echo
    Note over ZA: DNS proxy → ServiceEntry api-b-remote VIP<br/>use-waypoint etiketi
    ZA->>WA: HBONE :15008
    Note over WA: VirtualService via-egress<br/>hedef → istio-egressgateway:443
    WA->>E: mTLS ISTIO_MUTUAL :443
    Note over E: Gateway egress hosts *<br/>VirtualService egress-routes · authority api-b
    E->>G: mTLS ISTIO_MUTUAL → 172.18.202.10:443
    Note over G: AuthZ allow-dmz-and-egress<br/>kaynak = istio-egressgateway
    G->>WB: HBONE :15008
    WB->>B: HBONE · ztunnel → :9898
    B-->>A: 202 · echo
```

| Adım | Nereden → Nereye | Port / Protokol | Şifreleme | Tanımlayan kaynak |
|------|------------------|-----------------|-----------|-------------------|
| 1 | api-a: `api-b.apps.example.local` DNS sorgusu | ztunnel DNS proxy, ServiceEntry için otomatik VIP | – | [manifests/cluster-a/50-egress.yaml](manifests/cluster-a/50-egress.yaml) `ServiceEntry api-b-remote` |
| 2 | api-a → ztunnel → waypoint | HBONE `:15008` | **mTLS** | ServiceEntry'deki `istio.io/use-waypoint: waypoint` etiketi |
| 3 | waypoint: hedefi egress gateway'e çevir | `VirtualService via-egress` | – | 50-egress.yaml |
| 4 | waypoint → istio-egressgateway | `:443` | **mTLS** (`ISTIO_MUTUAL`) | `DestinationRule egressgateway` |
| 5 | egress gw: TLS'i kabul et | Gateway server `hosts: ["*"]`. Waypoint, Istio'nun iç SNI'ını (`outbound_.443_._.istio-egressgateway...`) gönderdiği için host listesi kısıtlanamaz | – | `Gateway egress` |
| 6 | egress gw: Host'a göre yönlendir | `authority: api-b.apps.example.local` | – | `VirtualService egress-routes` |
| 7 | egress gw → cluster-b ingress gw | `172.18.202.10:443` | **mTLS** (`ISTIO_MUTUAL`, SNI `api-b.apps.example.local`) | `ServiceEntry` + `DestinationRule cluster-b-gateway` (istio-egress ns) |
| 8 | cluster-b ingress gw: kimlik kontrolü | `corp.mesh/ns/istio-egress/sa/istio-egressgateway` izinli | – | [manifests/cluster-b/30-internal-gateway.yaml](manifests/cluster-b/30-internal-gateway.yaml) |
| 9 | → waypoint → ztunnel → api-b | Akış 1'in 7-10. adımlarıyla aynı | **mTLS** | manifests/cluster-b/ |

### Akış 4: api-a → httpbin.org (internete çıkış)

```mermaid
sequenceDiagram
    autonumber
    box rgb(219,234,254) cluster-a
        participant A as api-a pod
        participant Z as ztunnel
        participant W as waypoint<br/>ns api-a
        participant E as istio-egressgateway
    end
    participant X as httpbin.org

    A->>Z: GET http://httpbin.org/headers
    Z->>W: HBONE :15008 · ServiceEntry httpbin-ext
    W->>E: mTLS ISTIO_MUTUAL :443
    Note over E: VirtualService egress-routes<br/>authority httpbin.org
    E->>X: HTTP :80 · resolution DNS
    X-->>A: 200 · X-Envoy-Peer-Metadata-Id = istio-egressgateway
```

1. ServiceEntry `httpbin-ext` (api-a ns, waypoint etiketli) dış hedefi mesh'e tanıtır.
2. Waypoint `VirtualService via-egress` ile trafiği `istio-egressgateway:443` adresine mTLS ile yollar.
3. Egress gateway'deki `VirtualService egress-routes`, `authority: httpbin.org` eşleşmesiyle isteği `ServiceEntry httpbin-ext` (istio-egress ns, `resolution: DNS`) üzerinden `httpbin.org:80` adresine düz HTTP olarak çıkarır.
4. Yanıttaki `X-Envoy-Peer-Metadata-Id: router~...istio-egressgateway...` header'ı, isteğin egress gateway'den çıktığını gösterir.

cluster-b'de de aynı yapı var (yalnızca httpbin.org için): [manifests/cluster-b/50-egress.yaml](manifests/cluster-b/50-egress.yaml).

### Şifreleme özeti

| Bölüm | Durum |
|-------|-------|
| Kullanıcı → HAProxy → dmz-ingressgateway | **Düz HTTP.** DMZ'de TLS terminasyonu yol haritasında |
| DMZ ↔ internal cluster gateway'leri | mTLS (`ISTIO_MUTUAL`, ortak root CA) |
| cluster-a egress ↔ cluster-b ingress | mTLS (`ISTIO_MUTUAL`) |
| Cluster içi (gateway ↔ waypoint ↔ ztunnel ↔ pod) | mTLS (HBONE); `PeerAuthentication STRICT` (cluster-a/b) |
| Egress gateway → httpbin.org | Düz HTTP (dış hedef) |

---

## Güvenlik modeli

### Güven zinciri

```mermaid
flowchart TB
    root["Root CA<br/>O=corp-mesh · 10 yıl<br/>certs/root-cert.pem"]
    subgraph dmz["kind-dmz"]
        idmz["Intermediate CA dmz<br/>istio-system/cacerts"] --> sdmz["istiod"] --> wdmz["dmz-ingressgateway, ztunnel..."]
    end
    subgraph ca["kind-cluster-a"]
        ia["Intermediate CA cluster-a<br/>istio-system/cacerts"] --> sa["istiod"] --> wa["gateway'ler, waypoint, api-a"]
    end
    subgraph cb["kind-cluster-b"]
        ib["Intermediate CA cluster-b<br/>istio-system/cacerts"] --> sb["istiod"] --> wb["gateway'ler, waypoint, api-b"]
    end
    root --> idmz
    root --> ia
    root --> ib
```

Her workload sertifikası `spiffe://corp.mesh/ns/<namespace>/sa/<serviceaccount>` kimliğini taşır. Sertifikalar farklı intermediate CA'lardan gelse de ortak root sayesinde her cluster diğerinin sertifikasını doğrulayabilir.

### Kimlikler (SPIFFE)

| Kimlik | Nerede | Kullanım |
|--------|--------|----------|
| `corp.mesh/ns/istio-ingress/sa/dmz-ingressgateway` | dmz | DMZ'den internal cluster'lara giden trafik |
| `corp.mesh/ns/istio-ingress/sa/istio-ingressgateway` | cluster-a, cluster-b | Internal gateway'den uygulamalara giden trafik |
| `corp.mesh/ns/istio-egress/sa/istio-egressgateway` | cluster-a, cluster-b | Egress üzerinden diğer cluster'a giden trafik |
| `corp.mesh/ns/api-a/sa/api-a`, `.../api-b/sa/api-b` | cluster-a / cluster-b | Uygulama pod'ları |

### Yetkilendirme matrisi

| Hedef | İzin verilen kaynak | Kural | Uygulandığı yer |
|-------|---------------------|-------|-----------------|
| cluster-a ingress gw | yalnızca `dmz-ingressgateway` | L4/L7 | gateway Envoy |
| cluster-b ingress gw | `dmz-ingressgateway` + `istio-egressgateway` | L4/L7 | gateway Envoy |
| api-a servisi | yalnızca `istio-ingressgateway`, `GET`/`POST` | L7 | waypoint |
| api-b servisi | yalnızca `istio-ingressgateway`, `GET`/`POST` | L7 | waypoint |
| cluster-a/b mesh geneli | – | mTLS `STRICT` | ztunnel |

### Bilinen kısıtlar

- **Ortak trust domain:** cluster-b'nin kendi `istio-egressgateway`'i, cluster-a'nınkiyle aynı kimliği taşır. Bu yüzden cluster-b ingress gateway'i ikisini birbirinden ayıramaz. Ayrım gerekiyorsa cluster başına ayrı trust domain veya farklı SA adları kullanılmalı.
- **Egress zorunlu değil:** `outboundTrafficPolicy` henüz `ALLOW_ANY`; ServiceEntry'si olmayan bir dış adrese pod'lar doğrudan çıkabilir (yol haritası: `REGISTRY_ONLY`).
- **DMZ'de PeerAuthentication yok:** HAProxy mesh dışında çalıştığı için DMZ'de `STRICT` mTLS uygulanmıyor.

---

## Gözlemlenebilirlik (Kiali, Prometheus, Grafana)

Her cluster'da kendi Prometheus, Grafana ve Kiali'si çalışır. Cluster'lar ayrı mesh'ler olduğu için her Kiali yalnızca kendi cluster'ını gösterir.

| Cluster | Kiali | Grafana |
|---------|-------|---------|
| dmz | http://localhost:20001/kiali | http://localhost:3001 |
| cluster-a | http://localhost:20002/kiali | http://localhost:3002 |
| cluster-b | http://localhost:20003/kiali | http://localhost:3003 |

```mermaid
flowchart LR
    subgraph cluster["Her cluster · ns istio-system"]
        zt["ztunnel<br/>L4 metrikler"]
        gw["gateway'ler<br/>L7 metrikler"]
        wp["waypoint'ler<br/>L7 metrikler"]
        prom["Prometheus<br/>:9090"]
        kiali["Kiali<br/>NodePort 30201"]
        graf["Grafana<br/>NodePort 30300"]
        zt -->|scrape :15020| prom
        gw -->|scrape :15020| prom
        wp -->|scrape :15020| prom
        prom --> kiali
        prom --> graf
    end
    host["💻 localhost<br/>2000x / 300x"] -->|kind port mapping| kiali
    host -->|kind port mapping| graf
```

- **Erişim:** Kiali ve Grafana NodePort ile açılır, kind `extraPortMappings` ile host'a bağlanır (bkz. [clusters/](clusters/)). Internal cluster'lar uygulama trafiği için host'a kapalıdır; açık olan yalnızca bu yönetim araçlarıdır.
- **Kimlik doğrulama:** Kiali `anonymous`, Grafana anonim admin kullanır. Bu ayar lab içindir; gerçek ortamda OpenID veya OpenShift OAuth kullanılmalıdır.
- **Sürekli trafik:** DMZ'deki `loadgen` ([manifests/dmz/40-loadgen.yaml](manifests/dmz/40-loadgen.yaml)) her saniye Akış 1, 2 ve 3'ü tetikler, her 10 turda bir de `api-b /status/500` çağırır. Böylece grafiklerde hata oranı da görünür. Akış 4 (httpbin.org) dış servisi yormamak için loadgen'e eklenmedi; elle tetiklenir.

Kiali'de görülen graph (workload görünümü, loadgen çalışırken ölçüldü):

| Cluster | Kenarlar |
|---------|----------|
| dmz | `dmz-ingressgateway` → `cluster-a-gateway` (~1.4 rps) · `dmz-ingressgateway` → `cluster-b-gateway` (~0.75 rps, ~%9 hata) |
| cluster-a | `istio-ingressgateway` → `waypoint` → `api-a` (mTLS) · `api-a` → `waypoint` (TCP, ztunnel) · `api-a` → `istio-egressgateway` (HTTP, mTLS) · `istio-egressgateway` → `cluster-b-gateway` |
| cluster-b | `istio-ingressgateway` → `waypoint` → `api-b` (mTLS, ~%5 hata) |

Graph'ı okurken dikkat edilecekler:
- **Cluster'lar arası hedefler ServiceEntry adıyla görünür** (`cluster-a-gateway`, `cluster-b-gateway`). Kiali bu kenarlarda mTLS kilidi göstermez, ama trafik `ISTIO_MUTUAL` ile şifrelidir.
- **Gateway'e gelen trafiğin kaynağı görünmez.** Gateway'ler yalnızca kendi giden trafiğini raporlar. Bu yüzden DMZ'de HAProxy düğümü yoktur; cluster-b'de de trafiğin bir kısmının cluster-a egress'inden geldiği ayrıca görünmez.
- **Aynı çağrı iki katmanda görünür:** ztunnel L4 (`api-a → waypoint`, TCP bayt/sn), waypoint ise L7 (`api-a → istio-egressgateway`, HTTP istek/sn) olarak raporlar.
- **Hata oranı** loadgen'in `api-b /status/500` çağrısından gelir (her 10 turda bir).

---

## Bileşenler

| Bileşen | Cluster | Namespace | Kurulum |
|---------|---------|-----------|---------|
| MetalLB (LoadBalancer IP) | hepsi | metallb-system | manifest |
| istiod (profile=ambient) | hepsi | istio-system | helm `istio/istiod` |
| istio-cni (nftables) | hepsi | istio-system | helm `istio/cni` |
| ztunnel (DaemonSet) | hepsi | istio-system | helm `istio/ztunnel` |
| edge-lb (HAProxy) | dmz | edge-lb | `manifests/dmz` |
| dmz-ingressgateway | dmz | istio-ingress | helm `istio/gateway` |
| istio-ingressgateway (internal) | a, b | istio-ingress | helm `istio/gateway` |
| istio-egressgateway | a, b | istio-egress | helm `istio/gateway` |
| waypoint | a, b | api-a / api-b | Gateway API (`istio-waypoint`) |
| api-a / api-b (podinfo) | a / b | api-a / api-b | `manifests/cluster-*` |
| Prometheus, Grafana | hepsi | istio-system | Istio `samples/addons` |
| Kiali | hepsi | istio-system | helm `kiali/kiali-server` |
| loadgen (curl döngüsü) | dmz | loadgen | `manifests/dmz` |

## Dizin yapısı

```
service-mesh/
├── config.env                  # versiyonlar, mesh id, trust domain, IP planı
├── clusters/                   # kind cluster tanımları
│   ├── dmz.yaml                #   host 8080/8443 -> NodePort 30080/30443
│   ├── cluster-a.yaml
│   └── cluster-b.yaml
├── infra/
│   ├── metallb/                # IP havuzu şablonu (cluster başına ayrı /24)
│   └── observability/          # Grafana NodePort servisi
├── istio/
│   └── values/                 # helm values: istiod, cni, ztunnel, ingress/egress gw, kiali
├── manifests/
│   ├── dmz/
│   │   ├── 00-namespaces.yaml
│   │   ├── 10-edge-lb.yaml             # HAProxy
│   │   ├── 20-public-gateway.yaml      # Gateway + VirtualService (Host bazlı)
│   │   ├── 30-internal-clusters.yaml   # ServiceEntry + DestinationRule (mTLS)
│   │   └── 40-loadgen.yaml             # Kiali için sürekli trafik
│   ├── cluster-a/
│   │   ├── 00-namespaces.yaml          # ambient + waypoint etiketleri
│   │   ├── 10-api-a.yaml               # podinfo, backend = api-b
│   │   ├── 20-waypoint.yaml            # waypoint + seccomp ConfigMap
│   │   ├── 30-internal-gateway.yaml    # ISTIO_MUTUAL gateway + AuthZ
│   │   ├── 40-security.yaml            # PeerAuthentication STRICT + L7 AuthZ
│   │   └── 50-egress.yaml              # ServiceEntry → waypoint → egress gw
│   └── cluster-b/                      # aynı yapı (api-b, sadece httpbin egress)
├── scripts/
│   ├── setup.sh                # hepsini sırayla çalıştırır
│   ├── lib.sh                  # ortak yardımcılar (__NET_PREFIX__ doldurma vb.)
│   ├── 00-check-prereqs.sh
│   ├── 01-create-clusters.sh   # kind + Gateway API CRD
│   ├── 02-install-metallb.sh
│   ├── 03-generate-certs.sh    # root CA + intermediate CA -> cacerts
│   ├── 04-install-istio.sh     # base, istiod, cni, ztunnel
│   ├── 05-install-gateways.sh  # ingress / egress gateway'ler
│   ├── 06-deploy-manifests.sh
│   ├── 07-install-observability.sh  # Prometheus, Grafana, Kiali
│   ├── 08-verify.sh            # uçtan uca testler + Kiali/Grafana erişimi
│   └── 99-destroy.sh           # --certs, --cache
├── docs/
│   ├── README.md               # adımların listesi
│   ├── 00-setup.md             # her adımın dokümanı: yapılanlar, değişen dosyalar,
│   ├── 01-kiali.md             #   sorunlar, doğrulama
│   └── security-gap-analysis.md  # 13 katmanlı güvenlik boşluk analizi
└── certs/                      # üretilen sertifikalar (gitignore)
```

## IP planı

kind docker ağı genelde `172.18.0.0/16` olur. Scriptler bunu otomatik tespit eder; gerekirse `config.env` içindeki `NET_PREFIX` ile elle verebilirsiniz. Manifest'lerdeki `__NET_PREFIX__` yer tutucusu uygulama sırasında doldurulur.

| Cluster | Pod CIDR | Service CIDR | MetalLB havuzu | Ingress GW IP |
|---------|----------|--------------|----------------|---------------|
| dmz | 10.10.0.0/16 | 10.110.0.0/16 | 172.18.200.10-50 | 172.18.200.10 |
| cluster-a | 10.20.0.0/16 | 10.120.0.0/16 | 172.18.201.10-50 | 172.18.201.10 |
| cluster-b | 10.30.0.0/16 | 10.130.0.0/16 | 172.18.202.10-50 | 172.18.202.10 |

> Windows/Docker Desktop'ta MetalLB IP'lerine host'tan erişilemez. Bu IP'ler yalnızca cluster'lar arasında (aynı docker ağında) kullanılır. Host'tan giriş noktası `localhost:8080` adresidir.

## Gereksinimler

- Docker Desktop (en az 8 GB RAM önerilir; 3 cluster × 2 node çalışır)
- `kind`, `kubectl`, `helm`, `istioctl`, `openssl`
- Git Bash (scriptler bash ile yazılmıştır)

```powershell
winget install Kubernetes.kind Helm.Helm
# istioctl: https://github.com/istio/istio/releases
```

## Kurulum

```bash
# Hepsi birden
bash scripts/setup.sh

# veya adım adım
bash scripts/01-create-clusters.sh
bash scripts/02-install-metallb.sh
bash scripts/03-generate-certs.sh
bash scripts/04-install-istio.sh
bash scripts/05-install-gateways.sh
bash scripts/06-deploy-manifests.sh
bash scripts/07-install-observability.sh
```

## Test

```bash
bash scripts/08-verify.sh

# Manuel
curl -H "Host: api-a.apps.example.local" http://localhost:8080/
curl -H "Host: api-b.apps.example.local" http://localhost:8080/
curl -X POST -H "Host: api-a.apps.example.local" -d 'selam' http://localhost:8080/api/echo   # api-a -> api-b
```

Faydalı komutlar:

```bash
kubectl config get-contexts                                   # kind-dmz, kind-cluster-a, kind-cluster-b
istioctl --context kind-cluster-a ztunnel-config workloads     # ambient'e alınmış pod'lar
istioctl --context kind-cluster-a waypoint list -n api-a
kubectl --context kind-dmz -n istio-ingress logs deploy/dmz-ingressgateway -f
kubectl --context kind-cluster-a -n api-a logs deploy/waypoint -f
kubectl --context kind-cluster-a -n istio-egress logs deploy/istio-egressgateway -f
```

## Windows / Docker Desktop notları

Kurulum sırasında karşılaşılan ve repoda çözülmüş sorunlar:

| Belirti | Sebep | Çözüm |
|---------|-------|-------|
| Pod'lar `ContainerCreating`'de kalıyor, `CONNMARK revision 0 not supported` | WSL2 kernel'inde `xt_CONNMARK` yok, istio-cni iptables kuralları kurulamıyor | `global.nativeNftables: true` ([cni.yaml](istio/values/cni.yaml), [istiod.yaml](istio/values/istiod.yaml)). Cluster iptables ile kurulduysa yeniden oluşturulmalı (CNI kalıntı ipset görünce iptables'a döner) |
| Worker node `kubelet not healthy` | kubelet `node-role.kubernetes.io/*` etiketini kendine ekleyemez | kind config'te `node-role: <rol>` etiketi |
| `image has non-numeric user ... cannot verify user is non-root` | İmaj kullanıcıyı isimle tanımlıyor | `runAsUser` sayısal verildi (haproxy=99, podinfo=100) |
| Waypoint `PROGRAMMED=False`, `violates PodSecurity restricted` | Istio'nun ürettiği waypoint pod'unda seccomp yok | Gateway `infrastructure.parametersRef` → ConfigMap ile seccomp eklenir |
| Egress gw `filter_chain_not_found`, waypoint 503 | Waypoint iç SNI gönderir, Gateway server hosts eşleşmez | Egress Gateway server `hosts: ["*"]` |
| `chart base matching 1.31.x not found` | 1.31 GA chart'ları helm reposunda yayınlanmamış | `ISTIO_VERSION=1.30.7` |
| `kind` config dosyasını bulamıyor (`/c/Users/...`) | `MSYS_NO_PATHCONV=1` Windows exe'lerine giden yol çevirisini de kapatır | `lib.sh` içinde `ROOT_DIR` için `pwd -W` |
| curl `exit 23` (`/tmp/...` veya `/dev/null`'a yazamıyor) | Git Bash'teki curl yerel Windows programı; aynı `MSYS_NO_PATHCONV` sorunu | Geçici klasör `pwd -W` ile; `http_code` yardımcısı curl'ü `env -u MSYS_NO_PATHCONV` ile çalıştırır |
| `kind delete` başarısız: `did not receive an exit event` | Docker Desktop container'ı zamanında durduramıyor | `99-destroy.sh` kalan container'ları etiketle bulup siler |
| Kurulum yavaş, Prometheus `timed out` | Her cluster image'ları internetten ayrı çekiyor | Registry önbelleği (pull-through cache). `kind load` denendi, çok yavaş |
| Registry önbelleği boş kalıyor | Node'lara `docker exec` ile yazılan `hosts.toml` boştu (`-i` yoktu) | `docker exec -i` |
| Istio image'ları önbelleğe girmiyor | Istio 1.30 `registry.istio.io` kullanıyor; `registry:2` proxy'si onunla çalışmıyor (Content-Length yok) | `hub: docker.io/istio` |

## Temizlik

```bash
bash scripts/99-destroy.sh           # cluster'ları siler (registry önbelleği korunur)
bash scripts/99-destroy.sh --certs   # sertifikaları da siler
bash scripts/99-destroy.sh --cache   # registry önbelleğini de siler
```

### Registry önbelleği

Kurulum, Docker'da cluster'lardan bağımsız üç kalıcı registry container'ı çalıştırır: `cache-docker-io`, `cache-quay-io`, `cache-ghcr-io` (pull-through cache, `registry:2`). kind node'larındaki containerd image'ları önce bu önbelleklerden çeker, önbellek yoksa asıl registry'ye düşer. Böylece her image internetten yalnızca bir kez iner ve sıfırlamadan sonraki kurulumlar hızlanır. Ayrıntılar: [docs/01-kiali.md](docs/01-kiali.md).

## Gerçek OpenShift'e geçişte farklar

| Konu | Bu lab | OpenShift |
|------|--------|-----------|
| Istio kurulumu | Helm chart'ları | OpenShift Service Mesh 3 (Sail Operator): `Istio`, `IstioCNI`, `ZTunnel` CR'ları |
| CNI | kindnet + istio-cni (nftables) | OVN-Kubernetes + istio-cni (`global.platform=openshift`) |
| Edge LB | HAProxy pod + NodePort | OpenShift Router / harici F5 |
| LoadBalancer | MetalLB (L2) | MetalLB operator veya bulut LB |
| Güvenlik | Pod Security `restricted` + elle seccomp | SCC (`restricted-v2`, seccomp otomatik) |

## Planlanan: Kullanıcı kimliği yayılımı (token exchange)

> Henüz uygulanmadı; hedef tasarım.

Dışarıdan gelen access token DMZ'de bırakılır. İçeriye yalnızca kullanıcı bilgisini taşıyan, DMZ'nin imzaladığı kısa ömürlü bir JWT girer. Tüm internal servisler kullanıcıyı bu JWT'den tanır.

### Bileşenler

| Bileşen | Yer | Görev |
|---------|-----|-------|
| **auth-service** | dmz, ns `auth` (yeni) | Envoy ext_authz HTTP servisi. Access token'ı doğrular (IdP introspection veya imza kontrolü), kullanıcı bilgisini alır ve **RS256 ile imzalı iç JWT** üretir. Token → JWT eşlemesini token ömrü boyunca önbellekler. JWKS (public key) yayınlar |
| dmz-ingressgateway | dmz | `CUSTOM` AuthorizationPolicy ile her isteği önce auth-service'e sorar. İzin verilirse `x-user-jwt` header'ını ekler, `Authorization` header'ını siler |
| Internal gateway + waypoint | cluster-a, cluster-b | `RequestAuthentication` ile JWT'nin imzasını, issuer'ını ve süresini doğrular. `AuthorizationPolicy` ile JWT'yi zorunlu kılar ve claim'lere göre yetki verir |
| Mikroservisler | cluster-a, cluster-b | JWT'deki claim'leri okur (doğrulama mesh'te yapıldığı için yeniden doğrulaması gerekmez). Başka servisi çağırırken `x-user-jwt`'yi aynen iletir |

### İç JWT örneği

```json
{
  "iss": "auth.dmz.corp.mesh",
  "aud": "internal-apis",
  "sub": "u-12345",
  "name": "Ayşe Yılmaz",
  "roles": ["customer", "premium"],
  "tenant": "corp",
  "iat": 1793448000,
  "exp": 1793448300
}
```

### Akış

```mermaid
sequenceDiagram
    autonumber
    actor U as İstemci
    box rgb(254,243,199) DMZ cluster
        participant H as HAProxy<br/>edge-lb
        participant D as dmz-ingressgateway
        participant AS as auth-service<br/>ns auth
    end
    participant IDP as IdP<br/>Keycloak vb.
    box rgb(219,234,254) cluster-a
        participant GA as istio-ingressgateway
        participant WA as waypoint
        participant A as api-a
        participant E as egressgateway
    end
    box rgb(220,252,231) cluster-b
        participant GB as istio-ingressgateway
        participant WB as waypoint
        participant B as api-b
    end

    U->>H: GET /orders · Authorization Bearer access_token
    H->>D: HTTP :80
    Note over D: AuthorizationPolicy CUSTOM<br/>provider auth-service
    D->>AS: ext_authz check · Authorization header

    opt önbellekte yok
        AS->>IDP: token introspection
        IDP-->>AS: active · sub, roles, tenant
    end

    alt token geçersiz veya süresi dolmuş
        AS-->>D: 401
        D-->>U: 401 Unauthorized
    else token geçerli
        Note over AS: iç JWT üret<br/>iss auth.dmz.corp.mesh · exp 5 dk<br/>RS256 private key ile imzala
        AS-->>D: 200 · x-user-jwt eklendi
        Note over D: Authorization header silindi<br/>x-user-jwt eklendi
        D->>GA: mTLS :443 · x-user-jwt
        Note over GA: RequestAuthentication<br/>imza, iss, aud, exp kontrolü
        GA->>WA: HBONE · x-user-jwt
        Note over WA: AuthorizationPolicy<br/>requestPrincipals + claim kontrolü
        WA->>A: x-user-jwt
        Note over A: kullanıcı = sub, roles<br/>JWT payload'undan okunur

        A->>E: api-b çağrısı · x-user-jwt aynen iletilir
        E->>GB: mTLS :443 · x-user-jwt
        Note over GB: aynı issuer'a güvenir<br/>JWT tekrar doğrulanır
        GB->>WB: HBONE · x-user-jwt
        WB->>B: x-user-jwt
        Note over B: aynı kullanıcıyı tanır
        B-->>A: 200
        A-->>U: 200 · kullanıcıya özel yanıt
    end
```

### Uygulama notları

- **İmza anahtarı yalnızca DMZ'de durur.** Internal cluster'lar sadece public key'i (JWKS) bilir. JWKS, `RequestAuthentication` içine **inline** yazılır; böylece internal zone'dan DMZ'ye doğru bir ağ çağrısı açmak gerekmez. Anahtar değiştirilirken eski ve yeni key bir süre birlikte yayınlanır.
- **Dış token içeri sızmaz.** `Authorization` header'ı DMZ gateway'de silinir (VirtualService `headers.request.remove`). Internal tarafta `x-user-jwt` dışında bir kimlik header'ı kabul edilmez.
- **Sahte header'a karşı koruma:** İstemci kendisi `x-user-jwt` gönderirse DMZ gateway bu header'ı auth-service'e gitmeden önce siler. İçeride ise imza doğrulaması, DMZ dışında üretilmiş JWT'leri zaten reddeder.
- **Kısa ömür:** JWT 5 dakika gibi kısa süreli olmalı; uzun süren iş akışları için yenilemeyi auth-service yapar.
- **Header aktarımı uygulamanın işi:** Mesh gelen header'ı giden çağrıya otomatik kopyalamaz. Her mikroservis, aldığı `x-user-jwt`'yi yaptığı çağrılara eklemeli (ör. HTTP client interceptor / middleware).

## Hedef katman modeli (planlanan)

> Henüz uygulanmadı; yol haritasındaki `zones`, `mgmt`, `dmz-channels` ve `data` adımlarıyla bu yapıya geçilecek.

| Katman | İnternet paketini doğrudan alır mı? | İçinde ne var |
|--------|-------------------------------------|---------------|
| **Dış DMZ (edge zone)** | Evet, yalnızca burası | LB, WAF, reverse proxy. Appliance olur, Kubernetes yok |
| **İç DMZ (uygulama DMZ'si) = dmz cluster** | Hayır, yalnızca edge'den gelen trafiği alır | Ingress GW, Mobile GW, Web BFF, Partner GW, Egress GW |
| **Internal (cluster-a / cluster-b)** | Hayır, yalnızca DMZ egress'ten mTLS ile | BFF'ler, domain servisleri |
| **Management (mgmt cluster)** | Hayır; dışarıya kapalı, dmz ve internal'dan erişilir | Veri (PostgreSQL, Redis), Keycloak, merkezi gözlemlenebilirlik |

```mermaid
flowchart LR
    inet(["🌐 İnternet"])

    subgraph EDGE["Dış DMZ · Kubernetes yok"]
        edge["edge appliance<br/>HAProxy + WAF · TLS"]
    end

    subgraph DMZ["İç DMZ · dmz cluster"]
        igw["Ingress GW"]
        mgw["Mobile GW"]
        bff["Web BFF"]
        pgw["Partner GW"]
        egw["Egress GW"]
        igw --> mgw & bff & pgw
        mgw & bff & pgw --> egw
    end

    subgraph INT["Internal"]
        A["cluster-a<br/>BFF'ler · domain servisleri"]
        B["cluster-b<br/>BFF'ler · domain servisleri"]
        A <==>|"mTLS · serbest"| B
    end

    subgraph MGMT["Management · mgmt cluster"]
        data["PostgreSQL · Redis"]
        kc["Keycloak"]
        obs["Prometheus · Kiali · Grafana"]
    end

    inet --> edge --> igw
    egw ==>|mTLS| A
    egw ==>|mTLS| B
    A & B ==>|"mTLS · TCP"| data
    DMZ & INT -.->|"metrikler · mTLS"| obs
```

Alınan kararlar:
- **Internal'a giriş yalnızca DMZ egress'ten.** Internal ingress gateway'ler `dmz-egressgateway` kimliğini kabul eder; `dmz-ingressgateway` artık doğrudan kabul edilmez.
- **cluster-a ↔ cluster-b trafiği internal zone içinde serbest.** Egress → ingress yolu, mTLS ile.
- **Tüm veri mgmt'te.** Domain veritabanları dahil PostgreSQL ve Redis mgmt cluster'ında durur. Internal servisler veriye mgmt'in gateway'i üzerinden, mTLS içinde TCP ile erişir.
- **Mobile GW ve Partner GW ayrı Istio gateway'ler.** Her kanalın kendi gateway deployment'ı ve kimliği olur; kanal bazlı politikalar (rate limit, JWT, partner mTLS) Istio ile uygulanır.
- **Metrikler mgmt'e gateway üzerinden, mTLS ile gider** (Prometheus `remote_write`).

## Yol haritası

Her adım ayrı bir branch'te yapılır; her branch bir önceki biten branch'ten açılır. Ayrıntılar: [docs/](docs/README.md).

| # | Branch | Adım | Durum |
|---|--------|------|-------|
| 00 | `setup` | Temel kurulum: 3 cluster, Istio ambient, gateway'ler, 4 akış | ✅ |
| 01 | `kiali` | Gözlemlenebilirlik: cluster başına Kiali, Prometheus, Grafana + loadgen; registry önbelleği | ✅ |
| 02 | `zones` | Edge'i Kubernetes dışına almak (HAProxy + Coraza WAF, ayrı Docker container); TLS 1.2+/1.3 ve HSTS; X-Forwarded-* temizliği, istek/bağlantı limitleri; DMZ egress gateway; internal AuthZ'nin `dmz-egressgateway` + karşı internal egress ile sınırlanması | ⏳ |
| 03 | `hardening` | `readOnlyRootFilesystem`; namespace başına `allow-nothing` AuthorizationPolicy; default-deny NetworkPolicy; gateway namespace'lerine `restricted`; DMZ'de STRICT mTLS; `REGISTRY_ONLY`; `server` header gizleme ve tek tip hata yanıtları | ⏳ |
| 04 | `mgmt` | mgmt cluster'ı; merkezi Prometheus (`remote_write`, gateway üzerinden), tek Kiali, tek Grafana; cluster başına Kiali/Grafana kaldırılır | ⏳ |
| 05 | `policy` | Kyverno: `latest` tag, privileged pod, hostPath reddi; cosign ile imzalı image zorunluluğu | ⏳ |
| 06 | `dmz-channels` | Mobile GW ve Partner GW (ayrı Istio gateway'ler), Web BFF; ingress host bazlı yönlendirme, internal'a egress üzerinden; kanal bazlı rate limit, CORS, güvenlik header'ları | ⏳ |
| 07 | `data` | mgmt'te PostgreSQL ve Redis; internal servislerden mgmt gateway üzerinden mTLS (TCP) erişim; servis başına DB kullanıcısı | ⏳ |
| 08 | `token-exchange` | DMZ'de auth-service (access token → iç JWT), Keycloak mgmt'te (MFA, kısa ömürlü token, kanal client'ları); header'ları aktaran örnek mikroservis; ayrıntılar: [Planlanan: Kullanıcı kimliği yayılımı](#planlanan-kullanıcı-kimliği-yayılımı-token-exchange) | ⏳ |
| 09 | `l7-policies` | Waypoint'te claim bazlı yetkilendirme (rol, kanal, `acr`) ve header kuralları; Redis ile kullanıcı ve partner bazlı global rate limit ve kota | ⏳ |
| 10 | `logging` | mgmt'te Loki + Fluent Bit; access log'lara `x-request-id`, `zone`, `channel`; Kubernetes audit log | ⏳ |
| 11 | `tracing` | mgmt'te Grafana Tempo + OpenTelemetry; gateway, waypoint ve servis span'leri; Grafana'da log ↔ trace geçişi | ⏳ |
| 12 | `traffic-mgmt` | Canary (v1/v2 ağırlıklı yönlendirme), fault injection (gecikme/hata), circuit breaker, outlier detection; etkiler Kiali ve Tempo'da izlenir | ⏳ |
| 13 | `secrets` | mgmt'te **HashiCorp Vault Community**: PKI (cert-manager + istio-csr ile Istio CA'nın Vault'a taşınması, root CA anahtarı diskten kalkar), KV v2 + External Secrets, Database motoru ile servis başına kısa ömürlü DB kullanıcıları, audit log. Cluster'lar Vault'a JWT/OIDC auth ile bağlanır | ⏳ |
| 14 | `pci-zone` | mgmt içinde sıkı izole namespace'ler olarak kart zone'u (CDE): yalnızca belirli servise mTLS ile erişim, default-deny AuthZ + NetworkPolicy, Vault Transit ile PAN tokenizasyonu (Enterprise'daki Transform yerine) | ⏳ |
| 15 | `ci` | GitHub Actions: Trivy (image + IaC), gitleaks, Semgrep, SBOM; branch protection | ⏳ |
| 16 | `gitops` | mgmt'te Argo CD; dört cluster'ın repo'dan yönetimi; isteğe bağlı Argo Rollouts ile otomatik canary | ⏳ |

**Tehdit modelleme (sürekli):** `zones` adımından itibaren her adım dokümanına bir STRIDE bölümü eklenir. Mevcut dört akışın STRIDE analizi `zones` dokümanında yapılır.

Adımların gerekçesi ve kapattıkları güvenlik maddeleri: [Güvenlik boşluk analizi](docs/security-gap-analysis.md).

Sonraki adaylar:
- [ ] *(En son, opsiyonel)* Ambient multicluster (east-west gateway): cluster-a ve cluster-b'yi tek mesh'te birleştirmek, DMZ'yi izole tutmak. Mevcut tasarım bilerek multicluster değildir; her cluster bağımsız bir mesh'tir ve cluster'lar yalnızca gateway'ler üzerinden konuşur
