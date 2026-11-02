# Service Mesh Lab: OpenShift Benzeri Çoklu Cluster Ortamı

Bu proje, kurumsal bir OpenShift yapısını yerelde **kind** ile simüle eder:

- **DMZ cluster**: dış dünyaya açık tek katman. Edge load balancer ve public Istio ingress gateway burada çalışır.
- **cluster-a** ve **cluster-b**: internal cluster'lar. API'ler burada çalışır, dışarıdan doğrudan erişilemez.
- **mgmt**: paylaşılan ürünler. Şu an merkezi gözlemlenebilirlik (tek Kiali, tek Grafana, merkezi Prometheus) ve veri (PostgreSQL, Valkey); ileride Keycloak, Vault.

> **Şu an aktif cluster'lar: `dmz`, `cluster-a` ve `mgmt`** (her biri tek node). **cluster-b RAM kısıtı nedeniyle şimdilik kapalı** ve yol haritasının son adımında (17 · `cluster-b`) geri gelecek. Bu README'deki mimari ve akış anlatımları cluster-b dahil hedef tasarımı gösterir; cluster-b'ye bağlı kısımlar *(cluster-b kapalı)* olarak işaretlidir. Bkz. [Kaynak kısıtları](#kaynak-kısıtları).
- **Istio Ambient Mesh**: sidecar yoktur. L4 mTLS'i **ztunnel**, L7 politikaları **waypoint** üstlenir. Giriş trafiği **ingress gateway**, çıkış trafiği **egress gateway** üzerinden geçer.

> **Adım adım geçmiş:** Her yol haritası maddesinin ayrıntılı dokümanı (yapılanlar, değişen dosyalar, sorunlar, doğrulama) [docs/](docs/README.md) altındadır.

## Mevcut durum

Giriş noktaları (host'ta `--resolve ...:8443:127.0.0.1` ve `certs/edge/ca.pem` ile; bkz. [Test](#test)):

| Kanal | Adres |
|-------|-------|
| web | **https://www.apps.example.local:8443** (giriş: `/auth/login`; API: `/api/*`, oturum cookie'siyle) |
| mobile | https://mobile-api.apps.example.local:8443/mobile/v1/ |
| partner | https://partner-api.apps.example.local:8443/partner/v1/ (istemci sertifikası: `certs/partner/acme.crt`) |
| branch (şube) | https://branch-api.corp.internal/branch/v1/: yalnızca şube ağından (`branch-net`, cihaz sertifikası `certs/branch/sube-0001.crt`, ikinci şube `sube-0002.crt`); host'tan ve internetten erişilemez |

`scripts/08-verify.sh` ile uçtan uca doğrulananlar:

| # | Test | Sonuç |
|---|------|-------|
| 1 | İnternet → edge (HAProxy + WAF) → web gateway → token handler → DMZ egress → cluster-a → web-bff → api-a (HTTPS) | ✅ |
| – | Kanallar: web (token handler, internal BFF, CORS, güvenlik header'ları), mobil (yalnızca `/mobile/v1/*`), partner (istemci sertifikası, izin listesi, kota 429); sahte `x-channel`/`x-partner-id` eziliyor; web gateway token handler'ı atlayıp internal'a çıkamıyor; DMZ'de BFF yok | ✅ |
| – | Şube kanalı: şube WAN'ı → iç firewall → branch-gateway (cihaz sertifikası, kimlik `x-branch-device` ile arka uca); sertifikasız/yabancı CA reddi; şube ağından diğer kapılara ve internetten şube kanalına yol yok | ✅ |
| 5 | Veri: account-api → PostgreSQL ve api-a → Valkey (mgmt), mesh üzerinden; servis başına kullanıcı (başka şema/yazma reddi, Valkey ACL); DMZ'den PostgreSQL'e yol yok; partner başına global kota (429) | ✅ |
| – | Kimlik (IdP token exchange): her kanalda kimlik zorunlu (401); değiştirilmiş token, yanlış client/realm, başka partner'ın sertifikası, başka şubenin cihazı reddediliyor; iç JWT'yi Keycloak imzalıyor (≤ 2 dk, `channel`, `scope`, `sid`, `loa_map`, kişisel veri yok); IdP'de kapatılan oturum 30 sn içinde reddediliyor; DMZ'de imza anahtarı yok; Keycloak yönetim konsolu internetten kapalı | ✅ |
| – | Web oturumu: tarayıcıda token yok, yalnızca `__Host-sid` (HttpOnly, Secure, SameSite=Strict); CSRF'siz POST 403; sahte cookie 401; logout sonrası 401; oturum deposu Valkey'de hash'li anahtarla, ayrı ACL kullanıcısıyla | ✅ |
| – | L7 yetki: partner bazlı scope (acme yalnızca hesap okuma, initech yalnızca ürün kataloğu; Keycloak atanmamış scope'u vermiyor); waypoint'te scope / kanal / rol kuralları; BOLA (başka müşterinin hesabı 404); transfer için seviye 2 (OTP) ve RFC 9470 step-up (yalnızca OTP sorulur); şube gişe transferi | ✅ |
| – | Mobil cihaz bağlama: cihaz anahtarıyla DPoP kanıtı her istekte (Bearer, kanıtsız, tekrarlanan, başka adres için kanıt 401); çalınan token başka cihazdan 403 (AC-04); attestation (kanıtsız / bütünlüğü bozuk 403, eski sürüm 426); cihaz kaydı yalnızca seviye 2 ile; silinen cihaz 30 sn içinde 403; tüm mobil trafik mobile-bff'ten | ✅ |
| – | Şube kontrolleri: tüm şube trafiği branch-bff'ten; personel yalnızca kendi şubesinin hesapları (başka şube 404); limit üstü transfer onaya düşer; dört göz (gişe onaylayamaz 403, talep eden kendi işlemini onaylayamaz 403 + veritabanı CHECK, başka şubenin yetkilisi 404, ikinci onay 409); mesai dışı 403 | ✅ |
| – | Edge: HTTP → HTTPS (301), HSTS, TLS 1.1 reddi, TLS 1.2/1.3 kabulü | ✅ |
| – | Edge: WAF XSS ve SQL injection denemelerini engelliyor (403) | ✅ |
| – | Edge: sahte `X-Forwarded-For` ve `x-user-jwt` içeri geçmiyor | ✅ |
| – | Edge: IP başına hız sınırı (ani 150 istekte 429) | ✅ |
| – | Zone geçişi: DMZ ingress'ten cluster-a'ya **doğrudan** gidiş reddediliyor (403 RBAC), egress üzerinden kabul | ✅ |
| – | Edge: 5xx gövdeleri tek tip, `Server`/`x-envoy-*` header'ları yok | ✅ |
| – | Edge → DMZ karşılıklı TLS: sertifikasız HTTPS ve düz HTTP reddediliyor, WAF sertifikasıyla kabul | ✅ |
| – | Internal varsayılan reddet: pod IP ile waypoint'i atlama engelleniyor, yetkisiz kimlik 403, egress gateway'e waypoint dışından erişilemiyor | ✅ |
| – | Gateway namespace'leri `restricted` Pod Security, ihlal eden pod yok | ✅ |
| – | Pod'dan kayıtsız hedefe doğrudan çıkış | ⚠️ açık (NetworkPolicy bu lab'da uygulanamıyor; bkz. [docs/03-hardening.md](docs/03-hardening.md)) |
| 2 | İnternet → ... → cluster-b → api-b | ⏸️ cluster-b kapalı |
| 3 | api-a → cluster-a egress → cluster-b → api-b | ⏸️ cluster-b kapalı |
| 4 | api-a → egress gateway → httpbin.org | ✅ |
| – | api-a ambient mesh'te ve waypoint kullanıyor | ✅ |
| – | Merkezi gözlemlenebilirlik: tek Kiali ve tek Grafana (mgmt), merkezi Prometheus'ta dmz ve cluster-a metrikleri, Kiali üç cluster'ı görüyor, mgmt girişi mesh dışına kapalı | ✅ |
| – | Politika (Kyverno, Deny): `latest`/tag'siz image, privileged, hostNetwork, hostPath ve izinsiz registry reddediliyor; api-a'da lab registry dışı ve imzasız image reddediliyor, imzalı image digest'e sabitlenerek kabul ediliyor | ✅ |

Adım adım doğrulama sonuçları: [docs/](docs/README.md). Prod hedefi ve gereksinimler: [docs/target-architecture.md](docs/target-architecture.md); pilotta karşılanma durumu ve farklar: [docs/pilot-architecture.md](docs/pilot-architecture.md). Araçların amacı ve muadilleri: [docs/tools.md](docs/tools.md).

Kullanılan sürümler:

| Bileşen | Sürüm | Not |
|---------|-------|-----|
| kind / Kubernetes | 0.33.0 / v1.36.4 | Her cluster **tek node** (control-plane, pod'lar da burada çalışır). RAM kısıtı nedeniyle; ileride 2 node'a çıkılacak (bkz. [Kaynak kısıtları](#kaynak-kısıtları)) |
| Istio (kontrol düzlemi) | 1.30.7 | 1.31 GA chart'ları helm reposunda yok. Image'lar `docker.io/istio`'dan (registry önbelleği uyumu) |
| istioctl | 1.31.3 | n-1 kontrol düzlemi desteği |
| Istio dataplane modu | ambient + **native nftables** | WSL2 kernel'inde iptables CONNMARK yok |
| Gateway API CRD | v1.6.0 | |
| MetalLB | v0.16.1 | L2 modu |
| Edge LB | HAProxy 3.0 | Docker container, Kubernetes dışında |
| WAF | OWASP ModSecurity CRS 4.25.2 (nginx, LTS) | ModSecurity v3, paranoia 1, engelleme modu |
| Uygulama | podinfo 6.7.1 | |
| Kiali | 2.26.0 | Istio 1.30 addon'undaki sürüm |
| Prometheus / Grafana | Istio 1.30 `samples/addons` | |
| Registry önbelleği | `registry:2.8.3` | docker.io, quay.io, ghcr.io için pull-through cache (bkz. [Registry önbelleği](#registry-önbelleği)) |
| Kyverno | 1.19.2 (chart 3.9.2) | Admission politikaları; CEL tabanlı `policies.kyverno.io/v1` API'si |
| cosign | 2.5.3 | Image imzalama (container olarak çalışır, kurulum gerekmez) |
| Lab registry | `registry:2.8.3` | `lab-registry:5000`: imzalı uygulama image'ları (kurumsal iç registry'nin karşılığı) |
| PostgreSQL | 18.1 (alpine) | mgmt, tek replika StatefulSet |
| Valkey | 9.0.0 (alpine) | mgmt; Redis uyumlu, BSD lisanslı |
| Envoy ratelimit | `f4e76690` | DMZ; partner başına global kota |
| Go servisleri | Go 1.27.1, distroless static | `web-token-handler`, `auth-service`, `web-bff`, `mobile-bff`, `mobile-sim` (yalnızca stdlib), `account-api`, `device-registry` (pgx v5.7.6), `branch-bff` |
| Keycloak | 26.8.0 (optimize image) | mgmt; standard token exchange (RFC 8693), introspection, lightweight access token |

---

## Mimari

> Diyagramlar Mermaid ile yazıldı. GitHub doğrudan gösterir; VS Code önizlemesi için
> "Markdown Preview Mermaid Support" eklentisi gerekir.

### Fiziksel yapı

Her şey Docker Desktop (WSL2) üzerinde çalışır. kind cluster'ları `kind` docker ağında, edge (dış DMZ) container'ları ise ayrı bir `edge-net` ağındadır. Her cluster şimdilik **tek node**'dur (bkz. [Kaynak kısıtları](#kaynak-kısıtları)). Host'a uygulama trafiği için yalnızca **edge-lb**'nin portları (8080 → HTTPS'e yönlendirme, 8443 → TLS), yönetim için Kiali ve Grafana portları açıktır.

```mermaid
flowchart LR
    host["💻 Windows host<br/>:8443 (TLS) · :8080 → 301"]

    subgraph edgenet["Docker · edge-net · dış DMZ (Kubernetes yok)"]
        elb["edge-lb<br/>HAProxy"]
        lg["loadgen<br/>internet istemcisi"]
        ewaf["edge-waf<br/>ModSecurity + CRS"]
    end

    subgraph docker["Docker · kind ağı 172.18.0.0/16"]
        direction LR
        subgraph dmz["kind-dmz · pod 10.10/16 · svc 10.110/16"]
            dmzcp["dmz-control-plane · node-role=infra"]
        end
        subgraph ca["kind-cluster-a · pod 10.20/16 · svc 10.120/16"]
            cacp["cluster-a-control-plane · node-role=worker"]
        end
        subgraph cb["kind-cluster-b · ŞİMDİLİK KAPALI · pod 10.30/16 · svc 10.130/16"]
            cbcp["cluster-b-control-plane · node-role=worker"]
        end
        subgraph mg["kind-mgmt · pod 10.40/16 · svc 10.140/16"]
            mgcp["mgmt-control-plane · node-role=infra<br/>20001→Kiali · 3001→Grafana"]
        end
        subgraph caches["registry önbelleği · kalıcı"]
            rc["cache-docker-io<br/>cache-quay-io<br/>cache-ghcr-io<br/>lab-registry (imzalı image'lar)"]
        end
        lbd(["MetalLB VIP<br/>172.18.200.10"])
        lba(["MetalLB VIP<br/>172.18.201.10"])
        lbb(["MetalLB VIP<br/>172.18.202.10"])
        lbm(["MetalLB VIP<br/>172.18.203.10"])
    end

    host -->|"port mapping 8080/8443"| elb
    lg --> elb
    elb --> ewaf
    ewaf -->|"WAF iki ağa da bağlı"| lbd
    host -.->|"Kiali / Grafana"| mgcp
    lbd -.- dmz
    lba -.- ca
    lbb -.- cb
    lbm -.- mg
    dmz & ca & mg -.->|"image çekme"| caches
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

### Topoloji görselleri

**Özet zone mimarisi:** güven kademeleri ve her kanalın giriş yolu (tek bakışta).

[![Zone özeti](docs/images/zone-ozet.png)](docs/images/zone-ozet.svg)


**Ayrıntılı prod topolojisi (hedef):** [docs/images/topology-prod-full.png](docs/images/topology-prod-full.png) ([SVG](docs/images/topology-prod-full.svg)). Kanal → zone → cluster → domain namespace → veri: internet kanalları ortak edge ve ortak DMZ'den (kanal başına namespace), şube kendi zone'undan, ATM/POS özel ağdan PCI cluster'ına; modern mikroservisler (`ocp-apps`, domain bazlı namespace) ve legacy core banking (`ocp-core`) ayrı cluster'larda; Oracle, MSSQL, PostgreSQL, Kafka, RabbitMQ, Valkey; ELK, Prometheus/Thanos, Grafana, Tempo, SIEM, CI/CD, Vault; dışarıya yalnızca dış çıkış zone'undan. Renkler güven seviyesini, kalın kesikli çizgiler güven sınırlarını (internet, kurum WAN'ı, banka perimetresi, private zone, PCI) gösterir.

[![Ayrıntılı prod topolojisi](docs/images/topology-prod-full.png)](docs/images/topology-prod-full.svg)

### Mantıksal yapı

Tüm ağlar, kanallar, VIP'ler ve segment başına şifreleme: [docs/06-dmz-channels.md → Detaylı topoloji](docs/06-dmz-channels.md#detaylı-topoloji).

```mermaid
flowchart TB
    user(["👤 Kullanıcı"])
    internet(["🌐 httpbin.org"])

    subgraph EDGE["Dış DMZ · Docker · Kubernetes yok"]
        direction TB
        haproxy["edge-lb · HAProxy<br/>TLS · HSTS · hız sınırı<br/>header temizliği"]
        waf["edge-waf<br/>ModSecurity + OWASP CRS"]
        haproxy -->|"HTTP"| waf
    end

    subgraph DMZ["İç DMZ · kind-dmz"]
        direction TB
        dmzgw["web gateway · dmz-ingressgateway<br/>LB 172.18.200.10 · www"]
        bff["web-token-handler (Go) + waypoint<br/>cookie ↔ token · BFF yok"]
        mobgw["mobile-gateway<br/>LB 172.18.200.11 · mobile-api"]
        pargw["partner-gateway<br/>LB 172.18.200.12 · partner-api"]
        brgw["branch-gateway<br/>LB 172.18.200.13 · branch-api.corp.internal"]
        dmzeg["dmz-egressgateway<br/>tek kapı · zone-exit"]
        dmzgw --> bff ==>|"mTLS"| dmzeg
        mobgw ==>|"mTLS"| dmzeg
        pargw ==>|"mTLS"| dmzeg
        brgw ==>|"mTLS"| dmzeg
    end

    subgraph A["cluster-a · kind-cluster-a"]
        direction TB
        agw["istio-ingressgateway<br/>LB 172.18.201.10<br/>AuthZ: dmz-egressgateway"]
        subgraph nsbff["ns channel-bff · ambient"]
            webbff["web-bff (Go) + waypoint<br/>yalnızca channel=web"]
        end
        subgraph nsa["ns api-a · ambient"]
            awp["waypoint<br/>L7 AuthZ + routing"]
            aapi["api-a x2<br/>podinfo :9898"]
        end
        aeg["istio-egressgateway<br/>ns istio-egress"]
        agw -->|"HBONE · web-bff host'u"| webbff
        webbff -->|"HBONE"| awp
        agw -->|"HBONE"| awp
        awp <-->|"HBONE · ztunnel"| aapi
        awp -->|"mTLS :443"| aeg
    end

    subgraph B["cluster-b · kind-cluster-b · şimdilik kapalı"]
        direction TB
        bgw["istio-ingressgateway<br/>LB 172.18.202.10<br/>AuthZ: dmz-egress + egressgateway"]
        subgraph nsb["ns api-b · ambient"]
            bwp["waypoint<br/>L7 AuthZ + routing"]
            bapi["api-b x2<br/>podinfo :9898"]
        end
        beg["istio-egressgateway<br/>ns istio-egress"]
        bgw -->|"HBONE"| bwp
        bwp <-->|"HBONE · ztunnel"| bapi
        bwp -->|"mTLS :443"| beg
    end

    user -->|"HTTPS :8443"| haproxy
    branch(["🏦 Şube terminali<br/>branch-net"]) -->|"TCP 443 · iç firewall (branch-fw)<br/>cihaz sertifikası"| brgw
    waf ==>|"mTLS :443<br/>Host'a göre kanal"| dmzgw & mobgw & pargw
    dmzeg ==>|"mTLS :443<br/>SNI api-a.apps.example.local"| agw
    dmzeg ==>|"mTLS :443<br/>SNI api-b.apps.example.local"| bgw
    aeg ==>|"mTLS :443<br/>SNI api-b.apps.example.local"| bgw
    aeg -->|"HTTP :80"| internet
    beg -->|"HTTP :80"| internet

    classDef gw fill:#dbeafe,stroke:#2563eb,color:#1e3a8a
    classDef app fill:#dcfce7,stroke:#16a34a,color:#14532d
    classDef edge fill:#fef3c7,stroke:#d97706,color:#78350f
    classDef ext fill:#f3f4f6,stroke:#6b7280,color:#111827
    class dmzgw,mobgw,pargw,brgw,dmzeg,agw,bgw,aeg,beg gw
    class bff,webbff,awp,bwp,aapi,bapi app
    class haproxy,waf edge
    class user,internet,branch ext
```

Kalın oklar (`==>`) mTLS bağlantılarıdır. Cluster'lar birbirine yalnızca gateway'ler üzerinden, LoadBalancer IP'leri aracılığıyla ulaşır. DMZ'den internal'a giden **tek kapı** `dmz-egressgateway`'dir.

### Ambient veri düzlemi nasıl çalışıyor?

- **istio-cni** (DaemonSet): `istio.io/dataplane-mode: ambient` etiketli namespace'lerdeki pod'ların ağ namespace'ine nftables kuralları yazar. Pod'un giren ve çıkan trafiği aynı node'daki ztunnel'e yönlendirilir. Uygulama container'ına hiçbir şey eklenmez; sidecar yoktur.
- **ztunnel** (DaemonSet, node başına bir tane): L4 proxy'dir. Pod'lar arası trafiği **HBONE** ile taşır (mTLS içinde HTTP CONNECT tüneli, port 15008). Her pod'un kimliği SPIFFE sertifikasıyla temsil edilir: `spiffe://corp.mesh/ns/<ns>/sa/<sa>`.
- **waypoint** (namespace başına bir Envoy deployment'ı): L7 proxy'dir. `istio.io/use-waypoint: waypoint` etiketi olan namespace'lerin ve ServiceEntry'lerin trafiği ztunnel'den waypoint'e gider. HTTP bazlı AuthorizationPolicy, VirtualService yönlendirmesi ve retry/timeout gibi kurallar burada uygulanır.
- **Gateway'ler** (ingress/egress): ambient'e dahil değildir, kendi Envoy'larıyla çalışırlar. Mesh içine HBONE ile, cluster dışına ise `ISTIO_MUTUAL` (Istio sertifikalarıyla mTLS) veya düz HTTP ile bağlanırlar.

### Tasarım kararları

- **Cluster'lar arasında düz ağ yok.** Her cluster kendi bağımsız ambient mesh'ini çalıştırır. Cluster'lar birbirine yalnızca gateway'ler üzerinden, LoadBalancer IP'leri aracılığıyla bağlanır; tıpkı DMZ ile internal zone arasında firewall bulunan gerçek yapılarda olduğu gibi. Bir cluster diğerinin pod IP'lerini veya servislerini bilmez.
- **Ortak güven zinciri.** Tek bir root CA vardır ve her cluster'ın istiod'u kendi intermediate CA'sıyla sertifika üretir (`istio-system/cacerts`, `scripts/03-generate-certs.sh`). Gateway'ler arasındaki `ISTIO_MUTUAL` bağlantısı bu ortak root sayesinde iki taraflı doğrulanır.
- **Ortak trust domain: `corp.mesh`.** Kimlikler servis hesabı (SA) adlarıyla ayrışır: DMZ'deki gateway'ler `dmz-ingressgateway` ve `dmz-egressgateway`, internal gateway'ler `istio-ingressgateway` ve `istio-egressgateway` adını taşır. AuthorizationPolicy'ler bu adlara göre yazılır.
- **Edge Kubernetes dışında.** Dış DMZ (LB, WAF, TLS) gerçekte bir appliance katmanıdır; lab'da Docker container'larıyla simüle edilir ve cluster'lara yalnızca WAF bağlanır. Edge sertifikası mesh CA'sından ayrı bir "public CA" ile imzalanır.
- **Zone geçişinde tek kapı.** DMZ ingress gateway internal'a doğrudan gitmez; her şey `dmz-egressgateway`'den çıkar. Internal gateway'ler yalnızca bu kimliği kabul eder.
- **Gateway kurulumu:** ingress ve egress gateway'ler `istio/gateway` Helm chart'ı ve klasik `Gateway` / `VirtualService` API'si ile, waypoint'ler ise Kubernetes Gateway API (`gatewayClassName: istio-waypoint`) ile kurulur.
- **OpenShift benzerlikleri:** `*.apps.example.local` route domain'i, `restricted` Pod Security, sayısal UID ile non-root container'lar, infra/worker node etiketleri ve HAProxy tabanlı edge (OpenShift Router / F5 karşılığı).

---

## Trafik akışları (adım adım)

### Akış 1: Kanallar → api-a (north-south)

DMZ'ye dört kanaldan girilir (`06 · dmz-channels`). İnternet kanalları edge'i paylaşır, şube kanalı kurum WAN'ından gelir; hepsi internal'a aynı egress kapısından gider, DMZ'deki kapıları ayrıdır:

| Kanal | Host | DMZ'deki yol | Kanala özel kurallar |
|-------|------|--------------|----------------------|
| web | `www.apps.example.local` | web gateway (`dmz-ingressgateway`) → **web-token-handler** (cookie → iç JWT) → waypoint → egress → internal **web-bff** | Tarayıcıda token yok (oturum cookie'si, CSRF), CORS (yalnızca kendi origin'imiz), güvenlik header'ları, 50 rps |
| mobile | `mobile-api.apps.example.local` | `mobile-gateway` (ext_authz: DPoP, attestation, kayıtlı cihaz) → egress → internal **mobile-bff** | Yalnızca `/mobile/v1/*` (önek kaldırılır), `Authorization: DPoP`, 30 rps |
| partner | `partner-api.apps.example.local` | edge'de istemci sertifikası → `partner-gateway` → egress | Partner CA sertifikası zorunlu, izin listesi (`acme`), yalnızca `/partner/v1/*`, 5 rps |
| branch (şube) | `branch-api.corp.internal` | **edge yok:** şube WAN'ı → `branch-fw` (TCP 443) → `branch-gateway` → egress | Branch CA cihaz sertifikası (gateway'de), `x-branch-device`, yalnızca `/branch/v1/*`, 20 rps; internal'da **branch-bff** (mesai saati) |

Web kanalı adım adım (oturum açılmış; giriş akışı: [Kullanıcı kimliği yayılımı](#kullanıcı-kimliği-yayılımı-token-exchange)):

```mermaid
sequenceDiagram
    autonumber
    actor U as İstemci
    box rgb(254,243,199) Dış DMZ · Docker
        participant H as edge-lb<br/>HAProxy
        participant F as edge-waf<br/>ModSecurity
    end
    box rgb(255,237,213) İç DMZ · kind-dmz
        participant D as web gateway<br/>dmz-ingressgateway
        participant B as web-token-handler<br/>(+ waypoint)
        participant E as dmz-egressgateway
    end
    box rgb(219,234,254) cluster-a
        participant G as istio-ingressgateway
        participant C as web-bff<br/>(ns channel-bff)
        participant W as waypoint<br/>ns api-a
        participant P as api-a pod
    end

    U->>H: GET /api/ · Cookie __Host-sid · TLS :8443 · Host www.apps.example.local
    Note over H: TLS 1.2+ sonlandır · hız/bağlantı sınırı<br/>X-Forwarded-*, x-user-jwt, x-partner-id, x-channel sil
    H->>F: HTTP :8080 (edge-net)
    Note over F: OWASP CRS kuralları · Host → kanal gateway'i
    F->>D: mTLS :443 → 172.18.200.10 · istemci sertifikası CN=edge-waf
    Note over D: VirtualService web → web-token-handler<br/>x-channel: web · Authorization silinir · CORS · 50 rps
    D->>B: HBONE (ztunnel) :8080
    Note over B: cookie → oturum (Valkey) → auth-service:<br/>introspection + token exchange → iç JWT (Keycloak, 2 dk)<br/>web-bff Service (waypoint) · authority → web-bff.apps.example.local
    B->>E: mTLS ISTIO_MUTUAL :443 (waypoint kimliği)
    Note over E: AuthZ: yalnızca token handler waypoint, mobile-gw, partner-gw, branch-gw<br/>zone-exit → cluster-a.internal.mesh
    E->>G: mTLS ISTIO_MUTUAL → 172.18.201.10:443
    Note over G: AuthZ allow-only-dmz-egress + iç JWT (3 realm issuer'ı)
    G->>C: HBONE (channel-bff waypoint: channel=web)
    C->>W: HBONE :15008 (iç JWT taşınır)
    Note over W: AuthZ api-a-allow-ingress (ingress gw veya web-bff, GET/POST, iç JWT)
    W->>P: HBONE → HTTP :9898
    P-->>U: 200 OK · api-a @ cluster-a · HSTS + güvenlik header'ları
```

| Adım | Nereden → Nereye | Port / Protokol | Şifreleme | Tanımlayan kaynak |
|------|------------------|-----------------|-----------|-------------------|
| 1 | Windows host → edge-lb container | `localhost:8443` → `:8443` | **TLS 1.2+/1.3** (edge sertifikası, "Lab Public CA"); partner host'unda ayrıca istemci sertifikası | [scripts/06b-deploy-edge.sh](scripts/06b-deploy-edge.sh), [edge/haproxy.cfg](edge/haproxy.cfg), [edge/crt-list.txt](edge/crt-list.txt) |
| 2 | edge-lb: kontroller | Hız (100/10 sn) ve bağlantı (50) sınırı, `Host` zorunlu, gövde ≤ 1 MB, slow-loris; header temizliği; HSTS; partner host'una sertifikasız istek 403 | – | `frontend https_in` |
| 3 | edge-lb → edge-waf | `:8080` HTTP (`edge-net` ağı) | Yok (edge içi) | `backend waf` |
| 4 | edge-waf: OWASP CRS, kanal seçimi | Paranoia 1, engelleme modu; Host → gateway VIP'i | – | `WAF_MODE` ([config.env](config.env)), [edge/waf-channels.conf.template](edge/waf-channels.conf.template) |
| 5 | edge-waf → kanal gateway'i | `172.18.200.10/11/12:443` (`kind` ağı) | **Karşılıklı TLS** (Edge-DMZ Zone CA) | [edge/waf-proxy-backend-ssl.conf.template](edge/waf-proxy-backend-ssl.conf.template), Gateway'ler (`MUTUAL`) |
| 6 | Kanal gateway'i: yönlendirme ve kanal kuralları | web: `www` → web-token-handler; mobile/partner/branch: ext_authz (auth-service) ve önek kaldırılır, authority `api-a.apps.example.local`; `x-channel`; hız sınırı | – | [manifests/dmz/20-public-gateway.yaml](manifests/dmz/20-public-gateway.yaml), [21-mobile-channel.yaml](manifests/dmz/21-mobile-channel.yaml), [22-partner-channel.yaml](manifests/dmz/22-partner-channel.yaml), [25-rate-limits.yaml](manifests/dmz/25-rate-limits.yaml) |
| 7 | (web) gateway → web-token-handler → auth-service, waypoint | HBONE | **mTLS** | [manifests/dmz/10-web-token-handler.yaml](manifests/dmz/10-web-token-handler.yaml), [12-auth-service.yaml](manifests/dmz/12-auth-service.yaml) |
| 8 | Kanal arka ucu → dmz-egressgateway | `:443` | **mTLS** (`ISTIO_MUTUAL`) | `DestinationRule dmz-egressgateway` (istio-egress) |
| 9 | dmz-egressgateway: kimlik kontrolü ve yönlendirme | yalnızca token handler'ın waypoint'i, `mobile-gateway`, `partner-gateway`, `branch-gateway`; `zone-exit` → `cluster-a.internal.mesh` | – | [manifests/dmz/30-internal-clusters.yaml](manifests/dmz/30-internal-clusters.yaml) |
| 10 | dmz-egressgateway → cluster-a ingress gw | `172.18.201.10:443` | **mTLS** (`ISTIO_MUTUAL`, SNI `api-a.apps.example.local`) | `ServiceEntry` + `DestinationRule cluster-a-gateway` |
| 11 | cluster-a ingress gw: kimlik kontrolü | istemci sertifikası `corp.mesh/ns/istio-egress/sa/dmz-egressgateway` olmalı ve Keycloak imzalı iç JWT (`requestPrincipals`); web'de `web-bff.apps.example.local` → `channel-bff/web-bff` | – | [manifests/cluster-a/30-internal-gateway.yaml](manifests/cluster-a/30-internal-gateway.yaml) `allow-only-dmz-egress` |
| 12 | cluster-a ingress gw → waypoint | HBONE `:15008` | **mTLS** | `Service api-a` üzerindeki `istio.io/ingress-use-waypoint: "true"` |
| 13 | waypoint: L7 yetki kontrolü | kaynak `istio-ingressgateway` veya `channel-bff/web-bff`, metot `GET`/`POST`, iç JWT | – | [manifests/cluster-a/40-security.yaml](manifests/cluster-a/40-security.yaml) |
| 14 | waypoint → ztunnel → api-a pod | HBONE `:15008` → `:9898` | **mTLS** | [manifests/cluster-a/10-api-a.yaml](manifests/cluster-a/10-api-a.yaml) |

`api-a.apps.example.local` artık dışarıya açık değil; yalnızca zone'lar arası iç ad olarak kullanılıyor. Ayrıntılar: [docs/06-dmz-channels.md](docs/06-dmz-channels.md).

**Akış 2 (İnternet → api-b)** *(cluster-b kapalı)* aynı yolu izler. Farklar: Host `api-b.apps.example.local`, hedef `172.18.202.10:443` ve kaynaklar `manifests/cluster-b/` altında.

### Akış 3: api-a → api-b (cluster'lar arası, egress gateway üzerinden) *(cluster-b kapalı)*

Tetikleyici: `POST /api/echo` isteği api-a'ya gelir. podinfo bu isteği `PODINFO_BACKEND_URL=http://api-b.apps.example.local/echo` adresine iletir. Bu ayar ve akışın tüm tanımları `manifests/*/cluster-b/` klasörlerinde durur ve yalnızca cluster-b aktifken uygulanır; cluster-b kapalıyken api-a yalnızca echo yapar.

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
    Note over WA: VirtualService via-egress-api-b<br/>hedef → istio-egressgateway:443
    WA->>E: mTLS ISTIO_MUTUAL :443
    Note over E: Gateway egress hosts *<br/>VirtualService egress-api-b
    E->>G: mTLS ISTIO_MUTUAL → 172.18.202.10:443
    Note over G: AuthZ allow-dmz-and-egress<br/>kaynak = istio-egressgateway
    G->>WB: HBONE :15008
    WB->>B: HBONE · ztunnel → :9898
    B-->>A: 202 · echo
```

| Adım | Nereden → Nereye | Port / Protokol | Şifreleme | Tanımlayan kaynak |
|------|------------------|-----------------|-----------|-------------------|
| 1 | api-a: `api-b.apps.example.local` DNS sorgusu | ztunnel DNS proxy, ServiceEntry için otomatik VIP | – | [manifests/cluster-a/cluster-b/51-egress-cluster-b.yaml](manifests/cluster-a/cluster-b/51-egress-cluster-b.yaml) `ServiceEntry api-b-remote` |
| 2 | api-a → ztunnel → waypoint | HBONE `:15008` | **mTLS** | ServiceEntry'deki `istio.io/use-waypoint: waypoint` etiketi |
| 3 | waypoint: hedefi egress gateway'e çevir | `VirtualService via-egress-api-b` | – | 51-egress-cluster-b.yaml |
| 4 | waypoint → istio-egressgateway | `:443` | **mTLS** (`ISTIO_MUTUAL`) | `DestinationRule egressgateway` (50-egress.yaml) |
| 5 | egress gw: TLS'i kabul et | Gateway server `hosts: ["*"]`. Waypoint, Istio'nun iç SNI'ını (`outbound_.443_._.istio-egressgateway...`) gönderdiği için host listesi kısıtlanamaz | – | `Gateway egress` (50-egress.yaml) |
| 6 | egress gw: Host'a göre yönlendir | `authority: api-b.apps.example.local` | – | `VirtualService egress-api-b` |
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
    Note over E: VirtualService egress-httpbin
    E->>X: HTTP :80 · resolution DNS
    X-->>A: 200 · X-Envoy-Peer-Metadata-Id = istio-egressgateway
```

1. ServiceEntry `httpbin-ext` (api-a ns, waypoint etiketli) dış hedefi mesh'e tanıtır.
2. Waypoint `VirtualService via-egress` ile trafiği `istio-egressgateway:443` adresine mTLS ile yollar.
3. Egress gateway'deki `VirtualService egress-httpbin` isteği `ServiceEntry httpbin-ext` (istio-egress ns, `resolution: DNS`) üzerinden `httpbin.org:80` adresine düz HTTP olarak çıkarır.
4. Yanıttaki `X-Envoy-Peer-Metadata-Id: router~...istio-egressgateway...` header'ı, isteğin egress gateway'den çıktığını gösterir.

*(cluster-b kapalı)* cluster-b'de de aynı yapı var (yalnızca httpbin.org için): [manifests/cluster-b/50-egress.yaml](manifests/cluster-b/50-egress.yaml).

### Akış 5: Servis → veri (mgmt)

Tüm veri mgmt'te (`07 · data`). Servisler mgmt'in adresini bilmez; kendi namespace'lerindeki seçicisiz bir Service'e bağlanır, gerisini mesh yönlendirir:

```mermaid
sequenceDiagram
    autonumber
    box rgb(219,234,254) cluster-a
        participant A as account-api
        participant W as waypoint<br/>ns account-api
        participant E as istio-egressgateway
    end
    box rgb(237,233,254) mgmt
        participant G as istio-ingressgateway
        participant P as postgres<br/>ns data
    end

    A->>W: TCP postgres.account-api:5432 (HBONE)
    Note over W: AuthZ: yalnızca account-api
    W->>E: mTLS :15432
    Note over E: AuthZ: 15432 yalnızca account-api waypoint'i
    E->>G: mTLS → 172.18.203.10:5432 · SNI postgres.mgmt.internal
    Note over G: AuthZ: 5432 yalnızca cluster-a egress
    G->>P: HBONE :5432
    Note over P: rol account_api: yalnızca accounts.accounts SELECT
```

| İstemci | Hedef | Yol | Veri tabanı kullanıcısı |
|---------|-------|-----|-------------------------|
| account-api (cluster-a) | PostgreSQL | waypoint → egress `:15432` → mgmt `:5432` | `account_api` (yalnızca `accounts.accounts` SELECT) |
| api-a (cluster-a, podinfo önbelleği) | Valkey | waypoint → egress `:16379` → mgmt `:6379` | `api_a` (yalnızca `cache:api-a:*`) |
| ratelimit (dmz, global kota) | Valkey | waypoint → dmz-egress `:16379` → mgmt `:6379` | `ratelimit` (yalnızca `rl:*`) |
| DMZ'deki herhangi bir bileşen | PostgreSQL | **yol yok** (DMZ egress'te 15432 yok; mgmt 5432'yi DMZ'ye açmıyor) | – |

Ayrıntılar: [docs/07-data.md](docs/07-data.md).

### Şifreleme özeti

| Bölüm | Durum |
|-------|-------|
| İstemci → edge-lb | **TLS 1.2+/1.3** (edge sertifikası, "Lab Public CA"), HSTS |
| edge-lb → edge-waf | Düz HTTP (yalnızca `edge-net` içinde) |
| edge-waf → dmz-ingressgateway | **Karşılıklı TLS** (Edge-DMZ Zone CA) |
| dmz-ingressgateway → dmz-egressgateway | mTLS (`ISTIO_MUTUAL`) |
| dmz-egressgateway → internal cluster gateway'leri | mTLS (`ISTIO_MUTUAL`, ortak root CA) |
| cluster-a egress ↔ cluster-b ingress | mTLS (`ISTIO_MUTUAL`) |
| Cluster içi (gateway ↔ waypoint ↔ ztunnel ↔ pod) | mTLS (HBONE); `PeerAuthentication STRICT` (cluster-a/b) |
| Egress gateway → httpbin.org | Düz HTTP (dış hedef) |
| Servis → mgmt veri katmanı (PostgreSQL, Valkey) | mTLS (waypoint → egress → mgmt ingress → HBONE); veritabanının kendi TLS'i yok |

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
| `corp.mesh/ns/istio-ingress/sa/dmz-ingressgateway` | dmz | Web kanalı: edge'den gelen trafiği token handler'a verir |
| `corp.mesh/ns/edge-web/sa/web-token-handler`, `.../edge-web/sa/waypoint` | dmz | Web token handler (cookie ↔ token) ve çıkışlarını (Keycloak, Valkey, web-bff) egress'e taşıyan waypoint |
| `corp.mesh/ns/auth/sa/auth-service` | dmz | Introspection + token exchange (yalnızca kanal gateway'leri ve token handler çağırabilir) |
| `corp.mesh/ns/channel-bff/sa/web-bff` | cluster-a | Web BFF (internal): domain servislerini iç JWT ile çağırır |
| `corp.mesh/ns/istio-mobile/sa/mobile-gateway` | dmz | Mobil kanal |
| `corp.mesh/ns/istio-partner/sa/partner-gateway` | dmz | Partner kanalı |
| `corp.mesh/ns/istio-branch/sa/branch-gateway` | dmz | Şube kanalı |
| `corp.mesh/ns/istio-egress/sa/dmz-egressgateway` | dmz | DMZ'den internal cluster'lara giden **tek** kimlik |
| `corp.mesh/ns/istio-ingress/sa/istio-ingressgateway` | cluster-a, cluster-b | Internal gateway'den uygulamalara giden trafik |
| `corp.mesh/ns/istio-egress/sa/istio-egressgateway` | cluster-a, cluster-b | Egress üzerinden diğer cluster'a giden trafik |
| `corp.mesh/ns/api-a/sa/api-a`, `.../api-b/sa/api-b` | cluster-a / cluster-b | Uygulama pod'ları |

### Yetkilendirme matrisi

| Hedef | İzin verilen kaynak | Kural | Uygulandığı yer |
|-------|---------------------|-------|-----------------|
| dmz-egressgateway | token handler'ın waypoint'i, `mobile-gateway`, `partner-gateway`, `branch-gateway` (web gateway değil) | L4/L7 | gateway Envoy |
| web-token-handler | yalnızca web gateway (`dmz-ingressgateway`), port 8080 | L4 | ztunnel |
| token handler çıkışları (web-bff, Keycloak, Valkey Service'leri) | yalnızca `web-token-handler`; Keycloak'ta yalnızca customers realm'inin token ve logout uçları | L7 | waypoint (edge-web) |
| auth-service | kanal gateway'leri ve `web-token-handler`, port 8080 | L4 | ztunnel |
| auth-service çıkışı (Keycloak) | yalnızca `auth-service`; 3 realm'in token ve introspect uçları, POST | L7 | waypoint (auth) |
| mobile-gateway | yalnızca `/mobile/v1/*`, GET/POST | L7 | gateway Envoy |
| partner-gateway | `x-partner-id` ∈ {acme} (edge'de sertifikadan), `/partner/v1/*`, GET/POST | L7 | gateway Envoy |
| branch-gateway | Branch CA cihaz sertifikası (TLS), `/branch/v1/*`, GET/POST | TLS + L7 | gateway Envoy |
| cluster-a ingress gw | yalnızca `dmz-egressgateway` (cluster-b aktifken + `istio-egressgateway`) ve Keycloak imzalı iç JWT | L4/L7 | gateway Envoy |
| web-bff (channel-bff) | yalnızca `istio-ingressgateway`, customers realm'inin JWT'si, `channel=web` | L7 | waypoint (channel-bff) |
| cluster-b ingress gw | `dmz-egressgateway` + `istio-egressgateway` | L4/L7 | gateway Envoy |
| api-a namespace'i (varsayılan) | hiçbiri (`allow-nothing`) | L4 | ztunnel |
| api-a pod'ları | yalnızca `api-a/sa/waypoint` | L4 | ztunnel |
| api-a servisi | her kanal kendi kapısından: web → `web-bff`, mobil → `mobile-bff`, şube → `branch-bff`, partner → `istio-ingressgateway`; iç JWT; müşteri ve personel kanalları `GET`/`POST`, partner yalnızca `info:read` ile `GET` | L7 | waypoint |
| account-api servisi | aynı kaynaklar ve iç JWT; `GET /accounts*` → `accounts:read`; `GET /products` → `products:read`; `POST /accounts/{id}/transfers` → `transfers:write` + kanal web/mobil (seviye 2 serviste) ya da kanal şube + gişe/operasyon/yetkili rolü; `GET /approvals`, `POST /approvals/{id}/approve` → şube + `supervisor` | L7 | waypoint (+ BOLA, şube kapsamı, seviye ve dört göz uygulamada) |
| partner istekleri | yol + metot ↔ scope (`accounts:read`, `products:read`, `info:read`); listede olmayan reddedilir | L7 | auth-service (DMZ) |
| cluster-a egress gw | yalnızca `api-a/sa/waypoint` | L4/L7 | gateway Envoy |
| api-b servisi | yalnızca `istio-ingressgateway`, `GET`/`POST` | L7 | waypoint |
| cluster-a/b mesh geneli | – | mTLS `STRICT` | ztunnel |

### Bilinen kısıtlar

- **İşlem imzası yok (açık nokta):** Transfer yalnızca seviye 2 (parola + OTP, son 5 dk) ister. Kullanıcının tutar ve alıcıyı cihaz anahtarıyla imzalaması (dinamik bağlama) yok; çalınmış bir oturumla ya da içerik değiştirilerek yapılan transfer imza ile engellenmiyor. `09d · tx-signing` bilinçli olarak atlandı (CH-08, IAM-08).
- **Ortak trust domain:** cluster-b'nin kendi `istio-egressgateway`'i, cluster-a'nınkiyle aynı kimliği taşır. Bu yüzden cluster-b ingress gateway'i ikisini birbirinden ayıramaz. Ayrım gerekiyorsa cluster başına ayrı trust domain veya farklı SA adları kullanılmalı.
- **Pod'ların doğrudan çıkışı açık:** `REGISTRY_ONLY` açık, ama ambient'te yalnızca waypoint ve gateway'leri etkiliyor; pod'lar ServiceEntry'si olmayan adreslere doğrudan çıkabiliyor. Bunu kapatacak egress NetworkPolicy bu lab'da uygulanamıyor (kindnet desteklemiyor, WSL2 kernel'inde `CONFIG_NFT_QUEUE` yok). Referans: [infra/network-policies/reference/](infra/network-policies/reference/).
- **DMZ'de PeerAuthentication yok:** DMZ'de ambient workload olmadığı için henüz eklenmedi (`hardening` adımı).

### Admission politikaları (Kyverno)

Her cluster'da Kyverno, pod'ları Kubernetes API'ye kabul edilirken denetler. Istio'dan önce kurulur; sonraki her bileşen bu denetimden geçer. Ayrıntılar: [docs/05-policy.md](docs/05-policy.md).

| Politika | Kapsam | Reddeder |
|----------|--------|----------|
| `disallow-latest-tag` | tüm namespace'ler* | `:latest` ya da tag'siz image |
| `disallow-privileged` | tüm namespace'ler* | privileged, `allowPrivilegeEscalation: true`, hostPID/IPC/Network |
| `disallow-host-path` | tüm namespace'ler* | hostPath volume |
| `restrict-image-registries` | tüm namespace'ler* | docker.io, quay.io, ghcr.io ve lab-registry dışı |
| `require-lab-registry` | `policy.corp.mesh/image-source=lab-registry` etiketli (api-a) | lab-registry dışı image |
| `verify-image-signatures` | lab-registry image'ları | kurumsal cosign anahtarıyla imzasız image; kabul edileni digest'e sabitler |

\* `kube-system`, `kube-public`, `kube-node-lease`, `local-path-storage` ve `kyverno` hariç. Node erişimi gereken sistem bileşenleri (ztunnel, istio-cni, MetalLB speaker) yalnızca gereken kural için istisnalı ([infra/kyverno/exceptions.yaml](infra/kyverno/exceptions.yaml)). Mod `config.env` → `POLICY_ACTION` (Deny | Audit).

İmzalı image hattı: `03b-publish-images.sh` uygulama image'larını registry önbelleğinden `lab-registry:5000/lab/...` altına kopyalar ve `certs/cosign/cosign.key` ile imzalar (CI'ın lab karşılığı). Açık anahtar Kyverno politikasına gömülür.

Ayrıntılı tehdit analizi: [docs/02-zones.md → STRIDE](docs/02-zones.md#stride-tehdit-modeli) ve [Güvenlik boşluk analizi](docs/security-gap-analysis.md).

---

## Gözlemlenebilirlik (Kiali, Prometheus, Grafana)

Gözlemlenebilirlik **mgmt cluster'ında merkezi**dir (`04 · mgmt`). Her cluster'daki Prometheus metrik toplar ve kendi egress gateway'i üzerinden mgmt'e gönderir. Tek Kiali ve tek Grafana merkezi Prometheus'tan okur.

| Arayüz | Adres | Not |
|--------|-------|-----|
| **Kiali** | http://localhost:20001/kiali | Üç cluster tek arayüzde (çoklu cluster), salt okunur (`view_only_mode`) |
| **Grafana** | http://localhost:3001 | Istio dashboard'ları, merkezi Prometheus |

```mermaid
flowchart LR
    subgraph D["dmz / cluster-a · ns istio-system"]
        zt["ztunnel · gateway'ler · waypoint'ler"] -->|scrape :15020| p["Prometheus (agent)<br/>yerel veri yok"]
        p -->|"remote_write · HTTP :80"| eg["egress gateway"]
    end
    subgraph M["mgmt"]
        mgw["istio-ingressgateway<br/>AuthZ: yalnızca egress kimlikleri"]
        cp["Prometheus (merkezi)<br/>remote-write receiver"]
        k["Kiali<br/>NodePort 30201"]
        g["Grafana<br/>NodePort 30300"]
        mgw --> cp --> k & g
    end
    eg ==>|"mTLS :443"| mgw
    k -.->|"Kubernetes API (salt okunur SA, mesh dışı)"| D
    host["💻 localhost:20001 / :3001"] -->|kind port mapping| k & g
```

- **Metrik akışı:** Prometheus → egress gateway (`prometheus-mgmt.istio-egress`, düz HTTP; host/yol/metot ile sınırlı) → mTLS → mgmt girişi (yalnızca `dmz-egressgateway` / `istio-egressgateway` kimlikleri, yalnızca `POST /api/v1/write`) → merkezi Prometheus. Ayrıntılar: [docs/04-mgmt.md](docs/04-mgmt.md).
- **Kiali çoklu cluster:** Uzak cluster'larda salt okunur `kiali` ServiceAccount'u (`kiali-viewer` ClusterRole); mgmt'te bunların kubeconfig'leri `kiali.io/multiCluster=true` etiketli secret'larda.
- **Kimlik doğrulama:** Kiali `anonymous`, Grafana anonim admin kullanır. Bu ayar lab içindir; gerçek ortamda OpenID veya OpenShift OAuth kullanılmalıdır.
- **Sürekli trafik:** `loadgen` container'ı ([scripts/06b-deploy-edge.sh](scripts/06b-deploy-edge.sh)) bir internet istemcisi gibi `edge-net` ağından edge-lb'ye HTTPS istekleri atar: her saniye web (+BFF dashboard), mobil ve partner (acme sertifikasıyla) kanallarını (cluster-b aktifse Akış 2'yi de) tetikler, her 10 turda bir de `/status/500` çağırır. Şube kanalının trafiğini `branch-terminal` ([scripts/06c-deploy-branch.sh](scripts/06c-deploy-branch.sh)) üretir. Böylece grafiklerde hata oranı da görünür. Akış 4 (httpbin.org) dış servisi yormamak için loadgen'e eklenmedi; elle tetiklenir.

Kiali'de görülen birleşik graph (workload görünümü, loadgen çalışırken ölçüldü; cluster-b kapalı):

| Kenar | Trafik |
|-------|--------|
| `dmz/dmz-ingressgateway` → `dmz/web-token-handler` → `dmz/waypoint` → `dmz/dmz-egressgateway` → `cluster-a/istio-ingressgateway` → `cluster-a/web-bff` | Akış 1, web kanalı |
| `dmz/mobile-gateway`, `dmz/partner-gateway`, `dmz/branch-gateway` → `dmz/dmz-egressgateway` | Akış 1, mobil, partner ve şube kanalları |
| `cluster-a/istio-ingressgateway` → `cluster-a/waypoint` → `cluster-a/api-a` | Akış 1, mTLS |
| `dmz/dmz-egressgateway` → `dmz/mgmt-gateway` · `cluster-a/istio-egressgateway` → `cluster-a/mgmt-gateway` | Metrik gönderimi (~1 rps her biri) |
| `mgmt/istio-ingressgateway` → `mgmt/prometheus` | Merkeze gelen metrikler (~2 rps) |

Graph'ı okurken dikkat edilecekler:
- **Cluster'lar arası hedefler ServiceEntry adıyla görünür** (`cluster-a-gateway`, `mgmt-gateway`). Kiali bu kenarlarda mTLS kilidi göstermez, ama trafik `ISTIO_MUTUAL` ile şifrelidir. Karşı cluster'daki devamı (ör. cluster-a'nın ingress gateway'i) aynı graph'ta ayrı bir düğüm olarak görünür, ama iki düğüm arasında ok çizilmez: cluster'lar bağımsız mesh'ler.
- **Gateway'e gelen trafiğin kaynağı görünmez.** Gateway'ler yalnızca kendi giden trafiğini raporlar. Bu yüzden edge (HAProxy, WAF) ve Prometheus graph'ta kaynak olarak görünmez.
- **Aynı çağrı iki katmanda görünür:** ztunnel L4 (TCP bayt/sn), waypoint ise L7 (HTTP istek/sn) olarak raporlar.
- **Hata oranı** loadgen'in her 10 turda bir yaptığı `/status/500` çağrısından gelir.

---

## Bileşenler

| Bileşen | Cluster | Namespace | Kurulum |
|---------|---------|-----------|---------|
| MetalLB (LoadBalancer IP) | hepsi | metallb-system | manifest |
| istiod (profile=ambient) | hepsi | istio-system | helm `istio/istiod` |
| istio-cni (nftables) | hepsi | istio-system | helm `istio/cni` |
| ztunnel (DaemonSet) | hepsi | istio-system | helm `istio/ztunnel` |
| edge-lb (HAProxy) | – (Docker, `edge-net`) | – | `scripts/06b-deploy-edge.sh` |
| edge-waf (ModSecurity + CRS) | – (Docker, `edge-net` + `kind`) | – | `scripts/06b-deploy-edge.sh` |
| loadgen (internet istemcisi) | – (Docker, `edge-net`) | – | `scripts/06b-deploy-edge.sh` |
| dmz-ingressgateway (web kanalı) | dmz | istio-ingress | helm `istio/gateway` |
| mobile-gateway / partner-gateway / branch-gateway | dmz | istio-mobile / istio-partner / istio-branch | helm `istio/gateway` |
| branch-fw (iç firewall) + branch-terminal | – (Docker, `branch-net`; branch-fw ayrıca `kind`) | – | `scripts/06c-deploy-branch.sh` |
| web-token-handler (Go) + waypoint | dmz | edge-web | `services/web-token-handler`, `manifests/dmz/10-web-token-handler.yaml` |
| auth-service (Go) + waypoint | dmz | auth | `services/auth-service`, `manifests/dmz/12-auth-service.yaml` |
| web-bff (Go) + waypoint | cluster-a | channel-bff | `services/web-bff`, `manifests/cluster-a/16-channel-bff.yaml` |
| Keycloak | mgmt | iam | `images/keycloak`, `infra/keycloak/`, `manifests/mgmt/30-keycloak.yaml` |
| ratelimit (Envoy) + waypoint | dmz | ratelimit | `manifests/dmz/26-global-rate-limit.yaml` |
| account-api (Go) + waypoint | cluster-a | account-api | `services/account-api`, `manifests/cluster-a/15-account-api.yaml` |
| PostgreSQL, Valkey | mgmt | data | `manifests/mgmt/20-data.yaml` |
| dmz-egressgateway | dmz | istio-egress | helm `istio/gateway` |
| istio-ingressgateway (internal) | a, b | istio-ingress | helm `istio/gateway` |
| istio-egressgateway | a, b | istio-egress | helm `istio/gateway` |
| waypoint | a, b | api-a / api-b | Gateway API (`istio-waypoint`) |
| api-a / api-b (podinfo) | a / b | api-a / api-b | `manifests/cluster-*` |
| Prometheus | hepsi (mgmt'te merkezi, diğerlerinde `remote_write` ile ileten) | istio-system | Istio `samples/addons` (script'te uyarlanır) |
| Grafana | mgmt | istio-system | Istio `samples/addons` |
| Kiali | mgmt (uzak cluster'larda yalnızca salt okunur SA) | istio-system | helm `kiali/kiali-server` |
| mgmt ingress / egress gateway | mgmt | istio-ingress / istio-egress | helm `istio/gateway` |
| Kyverno (admission + reports controller) | hepsi | kyverno | helm `kyverno/kyverno` + `infra/kyverno/` |
| lab-registry | – (Docker, `kind`) | – | `scripts/lib.sh` (`start_lab_registry`) |

## Dizin yapısı

```
service-mesh/
├── config.env                  # versiyonlar, mesh id, trust domain, IP planı
├── clusters/                   # kind cluster tanımları
│   ├── dmz.yaml                #   host'a hiç port açmaz
│   ├── cluster-a.yaml
│   ├── cluster-b.yaml
│   └── mgmt.yaml               #   host'a Kiali (20001) ve Grafana (3001)
├── edge/
│   ├── haproxy.cfg             # edge LB: TLS, HSTS, limitler, header ve hata gövdesi temizliği
│   └── waf-proxy-backend-ssl.conf.template  # WAF -> DMZ karşılıklı TLS
├── infra/
│   ├── kyverno/                # helm values, politikalar, istisnalar
│   ├── metallb/                # IP havuzu şablonu (cluster başına ayrı /24)
│   ├── network-policies/reference/  # NetworkPolicy referansı (bu lab'da uygulanmıyor)
│   └── observability/          # Grafana NodePort servisi
├── istio/
│   └── values/                 # helm values: istiod, cni, ztunnel, ingress/egress gw, kiali
├── manifests/
│   ├── dmz/
│   │   ├── 00-namespaces.yaml          # istio-ingress/egress, istio-mobile, istio-partner, istio-branch, edge-web, auth
│   │   ├── 10-web-token-handler.yaml   # web token handler (cookie ↔ token), Keycloak/Valkey/web-bff çıkışları, AuthZ
│   │   ├── 12-auth-service.yaml        # ext_authz: introspection + Keycloak token exchange
│   │   ├── 20-public-gateway.yaml      # web kanalı: www → web-token-handler, CORS, x-channel; sso host'u
│   │   ├── 21-mobile-channel.yaml      # mobile-gateway: /mobile/v1/* → egress
│   │   ├── 22-partner-channel.yaml     # partner-gateway: izin listesi, /partner/v1/* → egress
│   │   ├── 23-branch-channel.yaml      # branch-gateway: cihaz sertifikası, /branch/v1/* → egress
│   │   ├── 25-rate-limits.yaml         # kanal başına local rate limit (EnvoyFilter)
│   │   ├── 26-global-rate-limit.yaml   # partner başına global kota: ratelimit servisi + Valkey (mgmt)
│   │   ├── 30-internal-clusters.yaml   # egress: zone-exit Gateway, AuthZ, cluster-a ServiceEntry/DR/VS
│   │   ├── 40-security.yaml            # PeerAuthentication STRICT
│   │   ├── 60-metrics-exit.yaml        # Prometheus -> dmz-egressgateway -> mgmt (remote_write)
│   │   └── cluster-b/                  # yalnızca cluster-b aktifken: api-b rotası ve çıkışı
│   ├── cluster-a/
│   │   ├── 00-namespaces.yaml          # ambient + waypoint etiketleri
│   │   ├── 10-api-a.yaml               # podinfo (backend opsiyonel, ConfigMap'ten; Valkey önbelleği)
│   │   ├── 15-account-api.yaml         # account-api (PostgreSQL), waypoint, AuthZ
│   │   ├── 16-channel-bff.yaml         # web-bff (internal), waypoint, AuthZ (yalnızca channel=web)
│   │   ├── 20-waypoint.yaml            # waypoint + seccomp ConfigMap
│   │   ├── 30-internal-gateway.yaml    # ISTIO_MUTUAL gateway + AuthZ
│   │   ├── 40-security.yaml            # STRICT mTLS, allow-nothing, L4/L7 AuthZ, egress gw AuthZ
│   │   ├── 45-request-authentication.yaml  # iç JWT: 3 Keycloak realm issuer'ı, inline JWKS
│   │   ├── 50-egress.yaml              # ServiceEntry → waypoint → egress gw → httpbin.org
│   │   ├── 55-data-exit.yaml           # veri çıkışı: postgres/valkey Service → waypoint → egress → mgmt
│   │   ├── 60-metrics-exit.yaml        # Prometheus -> istio-egressgateway -> mgmt (remote_write)
│   │   └── cluster-b/                  # yalnızca cluster-b aktifken: api-a backend, api-b'ye egress
│   ├── cluster-b/                      # cluster-b'nin kendisi (şimdilik kapalı): api-b, httpbin egress
│   └── mgmt/
│       ├── 00-namespaces.yaml          # istio-ingress, istio-egress, data (restricted)
│       ├── 10-metrics-entry.yaml       # mgmt girişi: Gateway + VS + AuthZ (yalnızca egress kimlikleri)
│       ├── 20-data.yaml                # PostgreSQL (servis başına rol) + Valkey (ACL), ns data
│       ├── 25-data-entry.yaml          # veri girişi: :5432 / :6379, port + kimlik bazlı AuthZ
│       └── 40-security.yaml            # STRICT mTLS, mgmt egress varsayılan reddi
├── scripts/
│   ├── setup.sh                # hepsini sırayla çalıştırır
│   ├── lib.sh                  # ortak yardımcılar (__NET_PREFIX__ doldurma vb.)
│   ├── 00-check-prereqs.sh
│   ├── 01-create-clusters.sh   # kind + Gateway API CRD
│   ├── 02-install-metallb.sh
│   ├── 03-generate-certs.sh    # root CA + intermediate CA -> cacerts; cosign anahtarı
│   ├── 03b-publish-images.sh   # image'ları lab-registry'ye kopyala + cosign ile imzala
│   ├── 03c-install-kyverno.sh  # Kyverno + politikalar + istisnalar (Istio'dan önce)
│   ├── 04-install-istio.sh     # base, istiod, cni, ztunnel
│   ├── 05-install-gateways.sh  # ingress / egress gateway'ler
│   ├── 05b-create-data-secrets.sh  # veri parolaları (certs/data/) ve Secret'lar
│   ├── 06-deploy-manifests.sh
│   ├── 06b-deploy-edge.sh      # edge-net, edge-waf, edge-lb, loadgen (Docker)
│   ├── 06c-deploy-branch.sh    # şube WAN'ı: branch-net, branch-fw, branch-terminal (Docker)
│   ├── 07-install-observability.sh  # merkezi Prometheus + remote_write, tek Grafana, tek Kiali (çoklu cluster)
│   ├── 08-verify.sh            # uçtan uca testler (✔/✘ özeti)
│   └── 99-destroy.sh           # --certs, --cache
├── services/
│   ├── web-token-handler/      # Go: web kanalının DMZ bileşeni (cookie ↔ token, oturum Valkey'de)
│   ├── auth-service/           # Go: ext_authz (introspection + Keycloak token exchange)
│   ├── web-bff/                # Go: web kanalının BFF'i (internal, channel-bff)
│   └── account-api/            # Go: hesapları PostgreSQL'den okuyan internal servis
├── tests/
│   ├── zone-direct-path.yaml   # "tek kapı" negatif testi için geçici rota
│   ├── web-bypass-bff.yaml     # web gateway'in token handler'ı atlayamadığını gösteren geçici rota
│   └── web-login.sh            # web'e tarayıcı gibi giriş (Authorization Code + PKCE), cookie bayrakları ve token sızıntısı
├── docs/
│   ├── README.md               # adımların listesi
│   ├── 00-setup.md             # her adımın dokümanı: yapılanlar, değişen dosyalar,
│   ├── 01-kiali.md             #   sorunlar, doğrulama
│   ├── target-architecture.md    # kurumsal hedef mimari: gereksinimler, akışlar, lab sapmaları
│   ├── pilot-architecture.md     # pilot (bu lab): gereksinim bazında durum ve fark nedenleri
│   └── security-gap-analysis.md  # 13 katmanlı güvenlik boşluk analizi
└── certs/                      # üretilen sertifikalar (gitignore)
```

## IP planı

kind docker ağı genelde `172.18.0.0/16` olur. Scriptler bunu otomatik tespit eder; gerekirse `config.env` içindeki `NET_PREFIX` ile elle verebilirsiniz. Manifest'lerdeki `__NET_PREFIX__` yer tutucusu uygulama sırasında doldurulur.

| Cluster | Pod CIDR | Service CIDR | MetalLB havuzu | Ingress GW IP |
|---------|----------|--------------|----------------|---------------|
| dmz | 10.10.0.0/16 | 10.110.0.0/16 | 172.18.200.10-50 | web .10 · mobile .11 · partner .12 · branch .13 |
| cluster-a | 10.20.0.0/16 | 10.120.0.0/16 | 172.18.201.10-50 | 172.18.201.10 |
| cluster-b *(kapalı, ayrılmış)* | 10.30.0.0/16 | 10.130.0.0/16 | 172.18.202.10-50 | 172.18.202.10 |
| mgmt | 10.40.0.0/16 | 10.140.0.0/16 | 172.18.203.10-50 | 172.18.203.10 |

> Windows/Docker Desktop'ta MetalLB IP'lerine host'tan erişilemez. Bu IP'ler yalnızca cluster'lar arasında (aynı docker ağında) kullanılır. Host'tan giriş noktası `localhost:8080` adresidir.

## Gereksinimler

- Docker Desktop. WSL'e en az 8 GB RAM ayrılmalı (bkz. aşağıdaki kaynak kısıtları)
- `kind`, `kubectl`, `helm`, `istioctl`, `openssl`
- Git Bash (scriptler bash ile yazılmıştır)

```powershell
winget install Kubernetes.kind Helm.Helm
# istioctl: https://github.com/istio/istio/releases
```

### Kaynak kısıtları

Lab, 15,7 GB fiziksel RAM'li ve 16 çekirdekli bir makinede geliştiriliyor. WSL'e 12 GB ayrılmış (`%USERPROFILE%\.wslconfig`: `memory=12GB`, `swap=4GB`).

`01-kiali` adımında 3 cluster × 2 node + cluster başına Prometheus/Grafana/Kiali + loadgen ile şu ölçüldü:

| Ölçüm | Değer |
|-------|-------|
| Windows'ta boş RAM | 0,2 GB |
| Docker VM'inde boş RAM | ~0,2 GB (4 GB önbellek) |
| Docker CPU kullanımı | ~%1100 (16 çekirdeğin ~11'i) |
| Etki | cluster-b'nin kube-apiserver'ı çöküp yeniden başladı; Kiali/Grafana 5-10 sn'de yanıt verdi |

Bu yüzden:
- **cluster-b şimdilik kapalı.** Aktif cluster'lar `dmz`, `cluster-a` ve `mgmt`. cluster-b, yol haritasının son adımında (17) geri gelecek. cluster-b'ye bağlı tanımlar `manifests/*/cluster-b/` klasörlerinde duruyor ve `CLUSTERS` listesinde cluster-b varsa otomatik uygulanıyor.
- **Her cluster şimdilik tek node.** Her node kendi kubelet, containerd, ztunnel, istio-cni ve kindnet'ini çalıştırdığı için node başına birkaç yüz MB tasarruf olur. kind, worker yoksa control-plane taint'ini kaldırır; tüm pod'lar o node'da çalışır. Zone ayrımı aynen korunur.
- **2 node'a çıkış** kaynak yeterli olduğunda yapılacak: her cluster dosyasına `- role: worker` eklenir.
- **Docker Desktop'ın kendi Kubernetes'i kapatılmalı** (Settings → Kubernetes); kapatıldı. Lab bunu kullanmaz, ama bellek ve CPU tüketir.
- `mgmt` adımında cluster başına Kiali/Grafana tek kopyaya indirildi; ancak mgmt cluster'ı eklendiği için kullanılabilir bellek ~6,7 GB'tan ~5,2 GB'a indi (`04-mgmt` ölçümü).
- `policy` adımında Kyverno üç cluster'a kuruldu: kullanılabilir bellek ~5,2 GB'tan ~3,6 GB'a indi. Kyverno pod'ları cluster başına ~160 MB; asıl maliyet, Kyverno'nun CRD şemalarını tutan kube-apiserver (`05-policy` ölçümü).
- `dmz-channels` adımında 3 yeni gateway, Web BFF ve waypoint eklendi: kullanılabilir bellek ~3,6 GB'tan ~3,2 GB'a indi (`06-dmz-channels` ölçümü).
- `data` adımında PostgreSQL, Valkey, account-api, ratelimit ve iki waypoint eklendi: kullanılabilir bellek ~3,2 GB'tan ~3,0 GB'a indi (`07-data` ölçümü).
- `token-exchange` adımında Keycloak (~650 MB) eklendi; aynı adımda bellek düzeltmeleri yapıldı (Prometheus agent modu, merkezde yalnızca Istio metrikleri ve 6 saat saklama, apiserver `GOMEMLIMIT`, optimize Keycloak image'ı): kullanılabilir bellek ~3,25 GB, yani Keycloak'tan önceki seviyede (`08-token-exchange` ölçümü).
- Ek tasarruf gerekirse: loadgen yalnızca izlerken açık tutulur (`kubectl --context kind-dmz -n loadgen scale deploy/loadgen --replicas=0`), uygulama kopyaları 1'e indirilir.

## Kurulum

```bash
# Hepsi birden
bash scripts/setup.sh

# veya adım adım
bash scripts/01-create-clusters.sh
bash scripts/02-install-metallb.sh
bash scripts/03-generate-certs.sh
bash scripts/03b-publish-images.sh
bash scripts/03c-install-kyverno.sh   # Audit modu için: ... Audit
bash scripts/04-install-istio.sh
bash scripts/05-install-gateways.sh
bash scripts/05b-create-data-secrets.sh
bash scripts/06-deploy-manifests.sh
bash scripts/06b-deploy-edge.sh
bash scripts/06c-deploy-branch.sh
bash scripts/07-install-observability.sh
```

## Test

```bash
bash scripts/08-verify.sh      # her test ✔/✘ olarak raporlanır, sonunda özet

# Manuel (Git Bash). --ssl-no-revoke: Windows curl'ü CRL kontrolü yapar, lab CA'sının CRL'i yok
H=www.apps.example.local
C="--ssl-no-revoke --cacert certs/edge/ca.pem --resolve $H:8443:127.0.0.1"
curl $C https://$H:8443/                                   # token handler'ın statik sayfası
curl $C https://$H:8443/api/                               # 401: oturum yok (web'de token değil cookie; giriş /auth/login)
# Web'e giriş tarayıcıdan ya da Linux curl'lü container'dan: tests/web-login.sh (bkz. 08-verify.sh web_login())
M=mobile-api.apps.example.local
curl --ssl-no-revoke --cacert certs/edge/ca.pem --resolve $M:8443:127.0.0.1 https://$M:8443/mobile/v1/
# Partner: Windows curl'ü PEM istemci sertifikası kullanamaz; Linux curl'lü container'dan (bkz. 08-verify.sh partner())
curl $C -s -o /dev/null -w '%{http_code}\n' "https://$H:8443/?id=1%27%20OR%20%271%27=%271"   # WAF: 403
curl -sI -H "Host: $H" http://127.0.0.1:8080/               # 301 -> https://...:8443/
```

Tarayıcıdan denemek için `certs/edge/ca.pem`'i güvenilir kök sertifika olarak ekleyin ve `hosts` dosyasına `127.0.0.1 www.apps.example.local` satırını yazın; ardından https://www.apps.example.local:8443 açılır.

Faydalı komutlar:

```bash
kubectl config get-contexts                                   # kind-dmz, kind-cluster-a, kind-mgmt (cluster-b kapalı)
istioctl --context kind-cluster-a ztunnel-config workloads     # ambient'e alınmış pod'lar
istioctl --context kind-cluster-a waypoint list -n api-a
kubectl --context kind-dmz -n istio-ingress logs deploy/dmz-ingressgateway -f
kubectl --context kind-cluster-a -n api-a logs deploy/waypoint -f
kubectl --context kind-cluster-a -n istio-egress logs deploy/istio-egressgateway -f
kubectl --context kind-dmz -n istio-egress logs deploy/dmz-egressgateway -f
docker logs -f edge-lb                                         # HAProxy erişim log'u
docker logs -f edge-waf                                        # nginx + ModSecurity (engellenenler JSON audit log)
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
| Edge HTTPS testinde curl `000`, `CERT_TRUST_REVOCATION_STATUS_UNKNOWN` | Windows curl'ü (schannel) sertifika iptal kontrolü yapar; lab CA'sının CRL/OCSP'si yok | `--ssl-no-revoke`. TLS sürüm testleri `openssl s_client` ile (Windows istemcisi TLS 1.1'i zaten kapatıyor olabilir) |

## Temizlik

```bash
bash scripts/99-destroy.sh           # cluster'ları siler (registry önbelleği korunur)
bash scripts/99-destroy.sh --certs   # sertifikaları da siler
bash scripts/99-destroy.sh --cache   # registry önbelleğini ve lab-registry'yi de siler
```

### Registry önbelleği

Kurulum, Docker'da cluster'lardan bağımsız üç kalıcı registry container'ı çalıştırır: `cache-docker-io`, `cache-quay-io`, `cache-ghcr-io` (pull-through cache, `registry:2`). kind node'larındaki containerd image'ları önce bu önbelleklerden çeker, önbellek yoksa asıl registry'ye düşer. Böylece her image internetten yalnızca bir kez iner ve sıfırlamadan sonraki kurulumlar hızlanır. Ayrıntılar: [docs/01-kiali.md](docs/01-kiali.md).

## Gerçek OpenShift'e geçişte farklar

| Konu | Bu lab | OpenShift |
|------|--------|-----------|
| Istio kurulumu | Helm chart'ları | OpenShift Service Mesh 3 (Sail Operator): `Istio`, `IstioCNI`, `ZTunnel` CR'ları |
| CNI | kindnet + istio-cni (nftables) | OVN-Kubernetes + istio-cni (`global.platform=openshift`) |
| Edge LB / WAF | HAProxy + ModSecurity CRS Docker container'ları (Kubernetes dışı) | Harici F5 / Citrix ADC + WAF appliance; DMZ içinde OpenShift Router |
| LoadBalancer | MetalLB (L2) | MetalLB operator veya bulut LB |
| Güvenlik | Pod Security `restricted` + elle seccomp | SCC (`restricted-v2`, seccomp otomatik) |

## Kullanıcı kimliği yayılımı (token exchange)

> `08 · token-exchange` ile başladı, `09a · idp-token-exchange` ile IdP tabanlı modele geçti. Ayrıntılar:
> [docs/08-token-exchange.md](docs/08-token-exchange.md), [docs/09a-idp-token-exchange.md](docs/09a-idp-token-exchange.md).

Dışarıdan gelen kimlik bilgisi (mobil ve partner access token'ı, şube personel token'ı, web'de oturum cookie'si) DMZ'de bırakılır. İçeriye yalnızca **Keycloak'ın imzaladığı**, 2 dakikalık bir **iç JWT** girer. Bu JWT'yi DMZ'deki auth-service, RFC 8693 token exchange ile Keycloak'tan alır; DMZ'de imza anahtarı yoktur.

```mermaid
sequenceDiagram
    autonumber
    actor U as İstemci
    participant KC as Keycloak (mgmt)
    participant G as kanal gateway'i (DMZ)
    participant AS as auth-service (DMZ)
    participant E as dmz-egressgateway
    participant GA as cluster-a ingress
    participant WA as waypoint
    participant A as servis

    U->>KC: login / token (sso host'u, edge → web gateway → egress → mgmt)
    KC-->>U: lightweight access token (aud = kanalın exchange client'ı, rol ve kişisel veri yok)
    U->>G: istek · Authorization: Bearer
    G->>AS: ext_authz (x-auth-channel gateway'den, x-partner-id / XFCC)
    AS->>KC: introspection (aktif mi, oturum açık mı, azp, rol)
    Note over AS: iss = kanalın realm'i · azp = kanalın client'ı<br/>(partner: = sertifika CN) · rol · şube cihazı
    AS->>KC: token exchange (RFC 8693, kanalın exchange client'ı, audience internal-apis)
    KC-->>AS: iç JWT (realm imzalı, 2 dk, channel, scope, sid, roles, loa_map)
    AS-->>G: 200 + x-user-jwt (30 sn önbellekli)
    Note over G: Authorization silinir
    G->>E: mTLS · x-user-jwt
    E->>GA: mTLS · x-user-jwt
    Note over GA: RequestAuthentication (3 realm issuer'ı, inline JWKS)<br/>requestPrincipals zorunlu
    GA->>WA: HBONE
    Note over WA: iç JWT tekrar doğrulanır · rol / kanal kontrolü
    WA->>A: x-user-jwt (servis claim'leri okur)
```

**Web kanalında** tarayıcı hiç token görmez:
- `web-token-handler` (DMZ) giriş akışını sunucu tarafında yürütür: Authorization Code + PKCE, `web-app` gizli client.
- Token'ları oturum deposunda (Valkey, `sess:*`) tutar; tarayıcıya yalnızca `__Host-sid` cookie'si (HttpOnly, Secure, SameSite=Strict) gider.
- Her `/api/*` isteğinde cookie'yi oturuma çevirir, auth-service'e kendisi sorar ve isteği iç JWT ile internal'daki `web-bff`'e iletir.

| Kanal | Realm | Dış client (`azp`) | Exchange client (`channel`) | Ek koşul | İç JWT'ye eklenen |
|-------|-------|--------------------|-----------------------------|----------|-------------------|
| web | `customers` | `web-app` (token handler) | `auth-web` (`web`) | rol `customer`, oturum cookie'si + CSRF | – |
| mobile | `customers` | `mobile-app` | `auth-mobile` (`mobile`) | rol `customer` | – |
| partner | `partners` | sertifika CN'i (`x-partner-id`) | `auth-partner` (`partner`) | client credentials, rol `partner` (token sertifikaya bağlı) | `partner_id` |
| branch | `staff` | `branch-teller` | `auth-branch` (`branch`) | rol `teller`/`operations`/`supervisor` + cihaz sertifikası; `branch_id` = cihaz | `branch_id` |

- **İç JWT'yi IdP imzalar.** DMZ ele geçirilse bile içeri girecek kimliği DMZ uyduramaz; kanal bilgisi (`channel`) de IdP'nin imzaladığı bir claim.
- **Internal yalnızca Keycloak realm anahtarlarına güvenir.** Açık anahtarlar `RequestAuthentication`'da inline JWKS. Realm anahtarları kurulumda üretilip Keycloak'a verildiği için internal'dan IdP'ye ağ çağrısı yok.
- **Dış token içeri girmez ve içerik taşımaz.** Kanal gateway'leri `Authorization`'ı siler. Dış token lightweight: içeriği yalnızca introspection ile okunur. `aud`'u yalnızca kendi kanalının exchange client'ı olduğundan başka kanalda çevrilemez.
- **Kısa ömür, iptal.** İç JWT 2 dk yaşar. Introspection, IdP'de kapatılan oturumu yakalar (önbellek nedeniyle en geç 30 sn).
- **Kişisel veri yok.** İç JWT'de ad ve e-posta yok; servisler kullanıcıyı `sub` ile tanır.
- **Header aktarımı uygulamanın işi.** Mesh header'ları kendiliğinden kopyalamaz; web-bff `x-user-jwt`'yi upstream çağrılarına taşır.
- **Consent:** first-party (web, mobil, şube) ve partner client credentials akışlarında yok. Üçüncü taraf açık bankacılık rızası: `09f · consent`.

## Hedef katman modeli (planlanan)

> **Kısmen uygulandı.** `02 · zones` ile dış DMZ (edge Kubernetes dışında, WAF, TLS), DMZ egress gateway ve "internal yalnızca DMZ egress'ten" kuralı; `04 · mgmt` ile management zone'u ve merkezi gözlemlenebilirlik hayata geçti. Kanal gateway'leri (`dmz-channels`) ve veri (`data`) sonraki adımlarda.

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
| 02 | `zones` | Edge'i Kubernetes dışına almak (HAProxy + ModSecurity/OWASP CRS WAF, ayrı Docker container'ları); TLS 1.2+/1.3 ve HSTS; X-Forwarded-* temizliği, istek/bağlantı limitleri; DMZ egress gateway; internal AuthZ'nin `dmz-egressgateway` + karşı internal egress ile sınırlanması | ✅ |
| 03 | `hardening` | `readOnlyRootFilesystem`; namespace başına `allow-nothing` AuthorizationPolicy; default-deny NetworkPolicy; gateway namespace'lerine `restricted`; DMZ'de STRICT mTLS; `REGISTRY_ONLY`; `server` header gizleme ve tek tip hata yanıtları | ✅ |
| 04 | `mgmt` | mgmt cluster'ı; merkezi Prometheus (`remote_write`, gateway üzerinden), tek Kiali, tek Grafana; cluster başına Kiali/Grafana kaldırılır | ✅ |
| 05 | `policy` | Kyverno: `latest` tag, privileged pod, hostPath reddi; cosign ile imzalı image zorunluluğu | ✅ |
| 06 | `dmz-channels` | Mobile GW, Partner GW ve şube kanalı (ayrı Istio gateway'ler), Web BFF; ingress host bazlı yönlendirme, internal'a egress üzerinden; kanal bazlı rate limit, CORS, güvenlik header'ları | ✅ |
| 07 | `data` | mgmt'te PostgreSQL ve Valkey (Redis uyumlu); internal servislerden mgmt gateway üzerinden mTLS (TCP) erişim; servis başına DB kullanıcısı; partner başına global rate limit | ✅ |
| 08 | `token-exchange` | DMZ'de auth-service (access token → iç JWT), Keycloak mgmt'te (kanal client'ları, kısa ömürlü token, brute force, personel OTP); internal'da iç JWT zorunlu; ayrıntılar: [Kullanıcı kimliği yayılımı](#kullanıcı-kimliği-yayılımı-token-exchange) | ✅ |
| 09a | `idp-token-exchange` | İç JWT'yi Keycloak üretir (introspection + RFC 8693 token exchange, kanal başına exchange client'ı, 2 dk, `channel`/`acr`/`sid`, kişisel veri yok); DMZ'de imza anahtarı yok; lightweight dış token'lar; web'de token handler (cookie oturumu, CSRF, refresh rotation), BFF internal'da (`channel-bff`); ayrıntılar: [docs/09a-idp-token-exchange.md](docs/09a-idp-token-exchange.md) | ✅ |
| 09b | `l7-policies` | Claim bazlı yetki: client başına API scope'ları (partner bazlı yetki: acme hesap okuma, initech ürün kataloğu), waypoint'te scope / kanal / rol kuralları, doğrulama seviyeleri (parola / OTP) ve RFC 9470 step-up, nesne seviyesinde yetki (BOLA), örnek transfer ucu; exchange'de scope yükseltme koruması; ayrıntılar: [docs/09b-l7-policies.md](docs/09b-l7-policies.md) | ✅ |
| 09c | `mobile-binding` | Mobil cihaz bağlama: cihaz anahtar çifti ve `device-registry` (mgmt); DPoP (RFC 9449, her istekte kanıt, `jti` tekrar kontrolü Valkey'de); kayıtlı cihaz kontrolü DMZ'de (Keycloak DPoP + token exchange birlikte çalışmıyor); app attestation ve minimum sürüm (simülasyon); `mobile-bff`; `mobile-sim` (uygulama simülatörü). Ayrıntılar: [docs/09c-mobile-binding.md](docs/09c-mobile-binding.md) | ✅ |
| 09d | ~~`tx-signing`~~ | **Atlandı, açık nokta.** Seviye 3 doğrulama: cihaz anahtarıyla işlem imzası ve dinamik bağlama (tutar + alıcı imzada), `tx-signing-svc`. Eşik ve hangi işlemin onay isteyeceği iş kararı. Hedef: CH-08, IAM-08 | ⏭ |
| 09e | `branch-controls` | `branch-bff` (tüm şube trafiği, mesai saati); personel rolleri (gişe, operasyon, yetkili) ve limit üstü transferde dört göz onayı (talep eden ≠ onaylayan, aynı şube; veritabanında da kısıt); personelin kendi şubesinin hesaplarıyla sınırlanması. Limit, onay süresi ve mesai saatleri konfigürasyon. Ayrıntılar: [docs/09e-branch-controls.md](docs/09e-branch-controls.md) | ✅ |
| 09f | `consent` | Açık bankacılık rızası: üçüncü taraf client (ör. `fintech-x`) için authorization code akışında müşteri rızası; rızaları tutan `consent-service` (Go, PostgreSQL): hesap, izin, süre; consent ID'nin iç JWT'ye taşınması, account-api'nin yalnızca rızadaki hesapları döndürmesi; rızanın geri alınması. First-party (web, mobil, şube) ve partner client credentials akışlarında consent yok (bkz. `08`) | ⏳ |
| 10 | `logging` | mgmt'te Loki + Fluent Bit; access log'lara `x-request-id`, `zone`, `channel`; Kubernetes audit log | ⏳ |
| 11 | `tracing` | mgmt'te Grafana Tempo + OpenTelemetry; gateway, waypoint ve servis span'leri; Grafana'da log ↔ trace geçişi | ⏳ |
| 12 | `traffic-mgmt` | Canary (v1/v2 ağırlıklı yönlendirme), fault injection (gecikme/hata), circuit breaker, outlier detection; etkiler Kiali ve Tempo'da izlenir | ⏳ |
| 13 | `secrets` | mgmt'te **HashiCorp Vault Community**: PKI (cert-manager + istio-csr ile Istio CA'nın Vault'a taşınması, root CA anahtarı diskten kalkar), KV v2 + External Secrets, Database motoru ile servis başına kısa ömürlü DB kullanıcıları, audit log. Cluster'lar Vault'a JWT/OIDC auth ile bağlanır | ⏳ |
| 14 | `pci-zone` | mgmt içinde sıkı izole namespace'ler olarak kart zone'u (CDE): yalnızca belirli servise mTLS ile erişim, default-deny AuthZ + NetworkPolicy, Vault Transit ile PAN tokenizasyonu (Enterprise'daki Transform yerine) | ⏳ |
| 15 | `ci` | GitHub Actions: Trivy (image + IaC), gitleaks, Semgrep, SBOM; branch protection | ⏳ |
| 16 | `gitops` | mgmt'te Argo CD; cluster'ların repo'dan yönetimi; isteğe bağlı Argo Rollouts ile otomatik canary | ⏳ |
| 17 | `cluster-b` | cluster-b'nin geri eklenmesi: `config.env` → `CLUSTERS`'a eklenir, `manifests/*/cluster-b/` otomatik uygulanır (Akış 2 ve 3). Önceki adımlarda cluster-a'ya eklenen her şeyin (hardening, policy, token, logging, tracing vb.) cluster-b'ye de uygulanması. RAM yeterliyse | ⏳ |

**Tehdit modelleme (sürekli):** `zones` adımından itibaren her adım dokümanına bir STRIDE bölümü eklenir. Mevcut dört akışın STRIDE analizi `zones` dokümanında yapılır.

Adımların gerekçesi ve kapattıkları güvenlik maddeleri: [Güvenlik boşluk analizi](docs/security-gap-analysis.md).

Sonraki adaylar:
- [ ] Cluster'ları 2 node'a çıkarmak (kaynak yeterli olduğunda; bkz. [Kaynak kısıtları](#kaynak-kısıtları))
- [ ] *(En son, opsiyonel)* Ambient multicluster (east-west gateway): cluster-a ve cluster-b'yi tek mesh'te birleştirmek, DMZ'yi izole tutmak. Mevcut tasarım bilerek multicluster değildir; her cluster bağımsız bir mesh'tir ve cluster'lar yalnızca gateway'ler üzerinden konuşur
