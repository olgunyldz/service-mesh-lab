# 00 · Temel Kurulum

| | |
|---|---|
| **Branch** | `setup` (açıldığı yer: `main`) |
| **Commit'ler** | `cc9145e` temel kurulum · `2c13637` `.gitattributes` · `95ab362` README güncellemesi |
| **Durum** | ✅ Tamamlandı. Sorun 5-7'nin düzeltmeleri son tam kurulumdan sonra elle uygulanmıştı; sıfırdan doğrulaması [01-kiali](01-kiali.md) adımındaki sıfırlamayla yapıldı ✅ |

## Amaç

OpenShift benzeri bir kurumsal yapıyı yerelde simüle etmek: dış dünyaya açık bir DMZ cluster'ı, iki internal cluster ve Istio ambient mesh. Cluster'lar arası trafik yalnızca gateway'ler üzerinden, mTLS ile akar.

## Adım sonundaki durum

| Konu | Durum |
|------|-------|
| Cluster'lar | `dmz`, `cluster-a`, `cluster-b` (kind); her biri 1 control-plane + 1 worker |
| Mesh | Her cluster'da bağımsız Istio 1.30.7 ambient (istiod, istio-cni, ztunnel); ortak root CA, trust domain `corp.mesh` |
| Giriş | `http://localhost:8080` (düz HTTP, `Host` header'ı ile) → DMZ içindeki HAProxy pod'u → `dmz-ingressgateway` |
| Zone geçişi | `dmz-ingressgateway` → internal ingress gateway'ler, doğrudan, `ISTIO_MUTUAL` |
| Uygulamalar | `api-a` (cluster-a), `api-b` (cluster-b): podinfo, namespace başına waypoint |
| Çıkış | cluster-a/b'de `istio-egressgateway` → httpbin.org; api-a → api-b de egress üzerinden |
| Çalışan akışlar | 1, 2, 3, 4 (bkz. Doğrulama) |
| Gözlemlenebilirlik | Yok |

## Önceki adıma göre değişenler

İlk adım: önceki durum boş bir repo (`main` branch'inde yalnızca boş başlangıç commit'i). Tüm yapı bu adımda kuruldu.

## Eklenen bileşenler

| Bileşen | Amacı | Neden gerekli | Muadilleri | Neden bu seçildi |
|---------|-------|---------------|------------|------------------|
| **kind** | Docker container'ları içinde Kubernetes cluster'ları | OpenShift'i yerelde birden çok cluster'la simüle etmek | k3d, minikube, OpenShift Local (CRC), MicroShift | Birden çok cluster'ı aynı Docker ağında hafifçe çalıştırır. CRC tek cluster ve çok ağır |
| **MetalLB** | `LoadBalancer` servislerine IP vermek | Cluster'lar birbirine gateway'lerin sabit LB IP'leri üzerinden ulaşıyor | kube-vip, Cilium LB IPAM, bulut LB'leri, NodePort | kind'da standart çözüm; L2 modu Docker ağında sorunsuz. OpenShift'te de MetalLB operatörü var |
| **Istio (ambient mod)** | Service mesh: mTLS, kimlik, yetkilendirme, trafik yönetimi | İstekte belirtilen gereksinim (ztunnel, waypoint, ingress/egress gateway) | Istio sidecar modu, Linkerd, Cilium Service Mesh, Consul Connect | Ambient sidecar'sız (daha az kaynak). OpenShift Service Mesh 3 de Istio tabanlı ve ambient'i destekliyor |
| **ztunnel** | Node başına L4 proxy; pod'lar arası mTLS (HBONE) | Ambient modun veri düzlemi | Sidecar Envoy | Ambient'in parçası |
| **waypoint** | Namespace başına L7 proxy (HTTP AuthZ, yönlendirme) | L7 politikalar (metot bazlı AuthZ vb.) için | Sidecar Envoy | Ambient'te L7'nin yolu; yalnızca gereken namespace'lerde çalışır |
| **Ingress / egress gateway'ler** (`istio/gateway` chart) | Cluster'a giriş ve çıkış noktaları | Zone'lar arası trafiğin denetlenebilir kapılardan geçmesi | Gateway API ile Istio gateway, NGINX/Envoy Gateway | İstekte belirtilen bileşen; klasik `Gateway`/`VirtualService` ile `ISTIO_MUTUAL` kolayca yapılandırılıyor |
| **Ortak root CA + cluster başına intermediate CA** (openssl) | Cluster'lar arası mTLS için ortak güven zinciri | Ayrı mesh'lerin gateway'leri birbirinin sertifikasını doğrulayabilsin | cert-manager, Istio'nun `tools/certs` Makefile'ı, Vault PKI | Bağımlılık gerektirmez. Vault'a geçiş `13 · secrets` adımında planlı |
| **HAProxy (edge-lb, DMZ içinde pod)** | Dış yük dengeleyici | F5 / OpenShift Router simülasyonu | nginx, Envoy, Traefik, F5 | Kurumsal ortamlarda yaygın. (`02 · zones`'ta Kubernetes dışına taşındı) |
| **podinfo** | Örnek API (api-a, api-b) | Akışları test etmek için gerçek bir HTTP servisi | httpbin, Istio bookinfo, özel servis | Küçük (Go), non-root, `/api/echo` ile başka servise çağrı yapabiliyor |

## Yapılanlar

```mermaid
flowchart LR
    s1["01 kind cluster'ları<br/>dmz · cluster-a · cluster-b"] --> s2["02 MetalLB<br/>cluster başına /24"]
    s2 --> s3["03 Sertifikalar<br/>ortak root CA<br/>+ intermediate CA'lar"]
    s3 --> s4["04 Istio ambient<br/>istiod · cni · ztunnel"]
    s4 --> s5["05 Gateway'ler<br/>DMZ ingress<br/>internal ingress + egress"]
    s5 --> s6["06 Manifest'ler<br/>edge-lb · API'ler<br/>waypoint · güvenlik · egress"]
    s6 --> s7["07 Doğrulama"]
```

| Adım | Script | Ne yapar |
|------|--------|----------|
| 1 | `01-create-clusters.sh` | 3 kind cluster'ı (her biri 1 control-plane + 1 worker; `01-kiali` adımında RAM nedeniyle tek node'a geçildi) ve Gateway API CRD'leri (v1.6.0) |
| 2 | `02-install-metallb.sh` | MetalLB v0.16.1; dmz `172.18.200.x`, cluster-a `.201.x`, cluster-b `.202.x` |
| 3 | `03-generate-certs.sh` | Ortak root CA ve her cluster için intermediate CA; `istio-system/cacerts` secret'ı |
| 4 | `04-install-istio.sh` | Istio 1.30.7 ambient: base, istiod, istio-cni (nftables), ztunnel |
| 5 | `05-install-gateways.sh` | `dmz-ingressgateway` (LB .200.10); cluster-a/b'de `istio-ingressgateway` (LB .201.10 / .202.10) ve `istio-egressgateway` |
| 6 | `06-deploy-manifests.sh` | `manifests/<cluster>/*.yaml` dosyalarını sırayla uygular |
| 7 | `07-verify.sh` | 4 trafik akışını uçtan uca test eder |

## Eklenen dosyalar

```
config.env                     # sürümler, mesh id, trust domain, IP planı
clusters/{dmz,cluster-a,cluster-b}.yaml
infra/metallb/ipaddresspool.yaml
istio/values/{istiod,cni,ztunnel,ingress-gateway,egress-gateway}.yaml
manifests/dmz/{00-namespaces,10-edge-lb,20-public-gateway,30-internal-clusters}.yaml
manifests/cluster-a/{00-namespaces,10-api-a,20-waypoint,30-internal-gateway,40-security,50-egress}.yaml
manifests/cluster-b/{00-namespaces,10-api-b,20-waypoint,30-internal-gateway,40-security,50-egress}.yaml
scripts/{lib,setup,00-check-prereqs,01..07,99-destroy}.sh
.gitignore  .gitattributes  README.md
```

## Ortaya çıkan yapı

```mermaid
flowchart LR
    user(["Kullanıcı"]) -->|":8080"| lb["edge-lb<br/>HAProxy"]
    subgraph DMZ["dmz"]
        lb --> dgw["dmz-ingressgateway"]
    end
    subgraph A["cluster-a"]
        agw["ingressgateway"] --> awp["waypoint"] --> api_a["api-a"]
        api_a -.-> aeg["egressgateway"]
    end
    subgraph B["cluster-b"]
        bgw["ingressgateway"] --> bwp["waypoint"] --> api_b["api-b"]
    end
    dgw ==>|mTLS| agw
    dgw ==>|mTLS| bgw
    aeg ==>|mTLS| bgw
    aeg -->|HTTP| ext(["httpbin.org"])
```

Ayrıntılı akışlar ve güvenlik modeli: [README → Trafik akışları](../README.md#trafik-akışları-adım-adım).

## Karşılaşılan sorunlar ve çözümler

| # | Belirti | Sebep | Çözüm | Değişen dosya |
|---|---------|-------|-------|---------------|
| 1 | `kind` config dosyasını bulamıyor (`/c/Users/...`) | `MSYS_NO_PATHCONV=1`, Windows exe'lerine giden yol çevirisini de kapatıyor | `ROOT_DIR` için `pwd -W` | `scripts/lib.sh` |
| 2 | Worker node'da `kubelet not healthy` | kubelet `node-role.kubernetes.io/*` etiketini kendine ekleyemez | Etiket `node-role: infra/worker` yapıldı | `clusters/*.yaml` |
| 3 | `chart base matching 1.31.3 not found` | Istio 1.31 GA chart'ları Helm reposunda yayınlanmamış | `ISTIO_VERSION=1.30.7` | `config.env` |
| 4 | Pod'lar `ContainerCreating`'de kalıyor, `CONNMARK not supported` | WSL2 kernel'inde `xt_CONNMARK` modülü yok; istio-cni iptables kurallarını yazamıyor | `global.nativeNftables: true`. Ayrıca cluster'ların yeniden kurulması gerekti: CNI, iptables kalıntısı görünce nftables'a geçmiyor | `istio/values/cni.yaml`, `istiod.yaml` |
| 5 | `image has non-numeric user` | İmajlar kullanıcıyı isimle tanımlıyor, `runAsNonRoot` doğrulanamıyor | `runAsUser` sayısal verildi (haproxy=99, podinfo=100) | `10-edge-lb.yaml`, `10-api-*.yaml` |
| 6 | Waypoint `PROGRAMMED=False` | Istio'nun ürettiği waypoint pod'u `restricted` Pod Security'yi ihlal ediyor (seccomp yok) | Gateway `infrastructure.parametersRef` → ConfigMap ile seccomp | `20-waypoint.yaml` |
| 7 | Egress gateway'de `filter_chain_not_found`, waypoint 503 | Waypoint Istio'nun iç SNI'ını gönderiyor; Gateway server hosts eşleşmiyor | Egress Gateway server `hosts: ["*"]` | `50-egress.yaml` |

## Doğrulama

`07-verify.sh` (o zamanki adıyla) sonucu:

| # | Test | Sonuç |
|---|------|-------|
| 1 | `localhost:8080` → api-a | ✅ `"api-a @ cluster-a"` |
| 2 | `localhost:8080` → api-b | ✅ `"api-b @ cluster-b"` |
| 3 | api-a → egress → cluster-b → api-b (`/api/echo`) | ✅ `"merhaba"` |
| 4 | api-a → egress → httpbin.org | ✅ `X-Envoy-Peer-Metadata-Id` = istio-egressgateway |
| – | Mesh dışından internal gateway'e doğrudan erişim | ✅ TLS handshake reddedildi |

## Bilinen kısıtlar

- DMZ girişi düz HTTP; TLS yol haritasında.
- `outboundTrafficPolicy` = `ALLOW_ANY`; egress gateway'den geçmek zorunlu değil.
- Ortak trust domain yüzünden cluster-b, kendi egress gateway'ini cluster-a'nınkinden ayıramıyor.
