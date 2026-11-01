# Araçlar, Framework'ler ve Kütüphaneler

Lab'de kullanılan her bileşenin ne işe yaradığı, bizde nasıl kullanıldığı ve muadilleri. Sürümlerin kaynağı [config.env](../config.env). En sonda lab'de çalışırken işe yarayan yardımcı araçlar var.

**İçindekiler**
1. [Çalışma ortamı ve CLI'lar](#1-çalışma-ortamı-ve-clilar)
2. [Kubernetes ve ağ](#2-kubernetes-ve-ağ)
3. [Service mesh (Istio ambient)](#3-service-mesh-istio-ambient)
4. [Edge (dış DMZ)](#4-edge-dış-dmz)
5. [Güvenlik ve politika](#5-güvenlik-ve-politika)
6. [Gözlemlenebilirlik](#6-gözlemlenebilirlik)
7. [Veri](#7-veri)
8. [Kimlik](#8-kimlik)
9. [Uygulamalar ve kütüphaneler](#9-uygulamalar-ve-kütüphaneler)
10. [Sonraki adımlarda gelecekler](#10-sonraki-adımlarda-gelecekler)
11. [Lab için faydalı yardımcı araçlar](#11-lab-için-faydalı-yardımcı-araçlar)

---

## 1. Çalışma ortamı ve CLI'lar

| Araç | Sürüm | Amacı | Bizde nasıl kullanılıyor | Muadilleri |
|------|-------|-------|--------------------------|------------|
| **Docker Desktop** (WSL2) | – | Container çalıştırma ortamı | kind node'ları, edge container'ları (HAProxy, WAF), registry'ler ve test container'ları burada çalışıyor. WSL'e 12 GB bellek verildi | Podman Desktop, Rancher Desktop, colima (macOS) |
| **kind** | 0.33 | Docker container'ları içinde Kubernetes cluster'ı | 3 tek node'lu cluster: `dmz`, `cluster-a`, `mgmt` ([clusters/](../clusters/)) | minikube, k3d (k3s), Docker Desktop Kubernetes; gerçek ortamda OpenShift, EKS/AKS/GKE |
| **kubectl** | – | Kubernetes API istemcisi | Tüm script'ler; `--context kind-<cluster>` ile cluster seçimi | `oc` (OpenShift), k9s (arayüz) |
| **Helm** | 3.x | Kubernetes paket yöneticisi (chart) | Istio, Kyverno, Kiali, gateway'ler; değerler `istio/values/`, `infra/kyverno/` | Kustomize, Operator'lar, Carvel, `istioctl install` |
| **istioctl** | 1.31.3 | Istio'nun CLI'ı: hata ayıklama, durum | `ztunnel-config workloads/services`, `waypoint list`; 08-verify'da ambient kontrolü | Kiali (görsel), `kubectl` + Envoy admin |
| **Git Bash** | – | Windows'ta POSIX kabuk | Tüm script'ler bash. `MSYS_NO_PATHCONV=1` ve `pwd -W` ile Windows yol sorunları çözülüyor | WSL içinde bash, PowerShell |
| **OpenSSL** | – | Sertifika ve anahtar üretimi, TLS testi | Tüm CA'lar ve sertifikalar ([03-generate-certs.sh](../scripts/03-generate-certs.sh)); TLS sürüm testleri (`s_client`) | step CLI, cfssl, cert-manager (cluster içinde) |
| **curl** | 8.11.1 (container) | HTTP istemcisi | Testler, loadgen, şube terminali. İstemci sertifikalı istekler Linux curl container'ından (Windows curl'ü PEM sertifikası kullanamıyor) | wget, httpie, hey/k6 (yük) |

## 2. Kubernetes ve ağ

| Bileşen | Sürüm | Amacı | Bizde nasıl kullanılıyor | Muadilleri |
|---------|-------|-------|--------------------------|------------|
| **Kubernetes** | v1.36.4 (kindest/node) | Container orkestrasyonu | Tüm cluster'lar; apiserver'a `GOMEMLIMIT=700MiB` (bellek sınırı) | OpenShift (bankalarda yaygın), Rancher RKE2, Tanzu |
| **kindnet** | kind ile gelir | CNI (pod ağı) | Varsayılan pod ağı. **NetworkPolicy uygulamıyor** (bilinen kısıt) | Calico, Cilium, OVN-Kubernetes (OpenShift) |
| **MetalLB** | v0.16.1 | Bare-metal'de `LoadBalancer` servis IP'si | Her cluster'a ayrı /24 havuz; gateway'lerin sabit VIP'leri (`172.18.20x.x`), L2 modu | kube-vip, Cilium LB IPAM, bulut LB'leri, F5 |
| **Gateway API** CRD | v1.6.0 | Kubernetes'in yeni giriş/yönlendirme API'si | Istio waypoint'leri (`gatewayClassName: istio-waypoint`) | Ingress API (eski), Istio `Gateway`/`VirtualService` (ikisi de kullanılıyor) |
| **local-path-provisioner** | kind ile gelir | Node diskinde PVC | PostgreSQL'in 1 GiB diski | Longhorn, Rook-Ceph, ODF (OpenShift), bulut diskleri |
| **Pod Security Admission** | Kubernetes yerleşik | Namespace etiketine göre pod güvenlik seviyesi | Tüm uygulama ve gateway namespace'leri `restricted` | OpenShift SCC, Kyverno/Gatekeeper politikaları |

## 3. Service mesh (Istio ambient)

| Bileşen | Sürüm | Amacı | Bizde nasıl kullanılıyor | Muadilleri |
|---------|-------|-------|--------------------------|------------|
| **Istio** (ambient mod) | 1.30.7 | Service mesh: mTLS, kimlik, yetkilendirme, trafik yönetimi | Her cluster'da bağımsız mesh; ortak root CA, trust domain `corp.mesh` | Linkerd, Cilium Service Mesh, Consul Connect, Kuma; OpenShift Service Mesh (Istio tabanlı) |
| **istiod** | 1.30.7 | Kontrol düzlemi: yapılandırma, sertifika dağıtımı | Cluster başına intermediate CA (`cacerts`); DMZ'de ext_authz sağlayıcıları | – |
| **istio-cni** | 1.30.7 | Pod trafiğini ztunnel'e yönlendirir | **Native nftables** modunda (WSL2 kernel'inde iptables CONNMARK yok) | – |
| **ztunnel** | 1.30.7 | Node başına L4 proxy (Rust): mTLS (HBONE), L4 yetkilendirme | Ambient pod'ların tüm trafiği; `allow-nothing` ve L4 politikaları | Sidecar modu (her pod'a Envoy) |
| **waypoint** | 1.30.7 (Envoy) | Namespace/servis başına L7 proxy | L7 AuthZ, JWT doğrulama, çıkış yönlendirmesi (`api-a`, `account-api`, `web-bff`, `ratelimit`, `auth`). `waypoint-for: service` | Sidecar Envoy |
| **Istio gateway'ler** (helm `istio/gateway`) | 1.30.7 (Envoy) | Giriş ve çıkış kapıları | DMZ: web/mobile/partner/branch kanal gateway'leri + egress (tek kapı). Internal: ingress + egress | Envoy Gateway, NGINX, Kong, OpenShift Router |
| **Envoy** | Istio ile | L7 proxy (gateway ve waypoint'lerin motoru) | Local rate limit, global rate limit ve ext_authz filtreleri `EnvoyFilter` ve `AuthorizationPolicy` ile | HAProxy, NGINX |

Önemli Istio kaynakları: `Gateway`, `VirtualService`, `DestinationRule` (`ISTIO_MUTUAL`), `ServiceEntry`, `PeerAuthentication` (`STRICT`), `AuthorizationPolicy` (ALLOW/DENY/CUSTOM), `RequestAuthentication` (JWT), `EnvoyFilter`.

## 4. Edge (dış DMZ)

| Bileşen | Sürüm | Amacı | Bizde nasıl kullanılıyor | Muadilleri |
|---------|-------|-------|--------------------------|------------|
| **HAProxy** | 3.0 | Yük dengeleyici, TLS sonlandırma | `edge-lb`: TLS 1.2+, HSTS, IP başına hız/bağlantı sınırı, header temizliği, partner istemci sertifikası (SNI'ya göre `crt-list`), 5xx gövde maskeleme ([edge/haproxy.cfg](../edge/haproxy.cfg)). `branch-fw`: TCP modunda iç firewall | F5 BIG-IP, NGINX, Citrix ADC, Envoy, bulut LB'leri |
| **ModSecurity + OWASP CRS** (nginx) | CRS 4.25.2 LTS | Web uygulama güvenlik duvarı (WAF) | `edge-waf`: engelleme modu, paranoia 1; Host'a göre kanal gateway'i seçimi; DMZ'ye mTLS | Coraza (Go, Envoy/Caddy'de), F5 ASM/Advanced WAF, Imperva, Cloudflare WAF, AWS WAF |
| **loadgen** | curl 8.11.1 | İnternet istemcisi simülasyonu | Kanallara sürekli trafik (Kiali grafikleri için); Keycloak'tan token alıp yeniliyor | hey, k6, vegeta, Locust |

## 5. Güvenlik ve politika

| Bileşen | Sürüm | Amacı | Bizde nasıl kullanılıyor | Muadilleri |
|---------|-------|-------|--------------------------|------------|
| **Kyverno** | 1.19.2 (chart 3.9.2) | Admission controller: kurala uymayan kaynakları reddeder | 6 CEL politikası (latest tag, privileged, hostPath, registry, iç registry zorunluluğu, imza doğrulama); dar istisnalar ([infra/kyverno/](../infra/kyverno/)) | OPA Gatekeeper (Rego), Kubewarden, ValidatingAdmissionPolicy (yerleşik), OpenShift SCC + ACM Governance |
| **cosign** (Sigstore) | 2.5.3 | Container image imzalama ve doğrulama | Image'lar iç registry'ye kopyalanıp imzalanıyor ([03b-publish-images.sh](../scripts/03b-publish-images.sh)); Kyverno doğruluyor | Notation (Notary v2), Docker Content Trust (eski) |
| **registry:2** (Distribution) | 2.8.3 | OCI image registry | `lab-registry`: imzalı image'lar (iç registry karşılığı). `cache-*`: docker.io/quay.io/ghcr.io önbellekleri | Harbor, Red Hat Quay, Nexus, Artifactory, Zot |
| **Sertifika otoriteleri** | OpenSSL ile | Güven zincirleri | Mesh root + cluster başına intermediate; Lab Public CA (edge); Edge-DMZ CA; Partner CA; Branch CA; iç JWT anahtarı | cert-manager, Vault PKI (13'te), step-ca, AD CS |

## 6. Gözlemlenebilirlik

| Bileşen | Sürüm | Amacı | Bizde nasıl kullanılıyor | Muadilleri |
|---------|-------|-------|--------------------------|------------|
| **Prometheus** | v3.10.0 | Metrik toplama ve sorgulama | **mgmt:** merkezi, remote-write alıcısı, 6 saat saklama. **dmz, cluster-a:** agent modu (yerel veri yok), yalnızca `istio_*`, `pilot_*`, `up` metriklerini mgmt'e gönderiyor; zone geçişi egress gateway'den, mTLS ile | Thanos, Grafana Mimir, VictoriaMetrics, OpenShift Monitoring/ACM Observability |
| **Grafana** | Istio addons | Pano ve görselleştirme | mgmt'te tek Grafana; Istio panoları (http://localhost:3001) | Kibana, OpenShift Console, Datadog |
| **Kiali** | 2.26.0 | Service mesh konsolu: trafik grafiği, yapılandırma doğrulama | mgmt'te tek Kiali, üç cluster tek grafikte, salt okunur (http://localhost:20001/kiali) | OpenShift Service Mesh Console, Grafana panoları, Gloo Mesh UI |

## 7. Veri

| Bileşen | Sürüm | Amacı | Bizde nasıl kullanılıyor | Muadilleri |
|---------|-------|-------|--------------------------|------------|
| **PostgreSQL** | 18.1 (alpine) | İlişkisel veritabanı | mgmt `data`: `corebank` (servis başına rol, en az yetki) ve Keycloak'ın veritabanı; tek replika StatefulSet | Oracle, MS SQL, Db2; operator'lü PostgreSQL: CloudNativePG, Crunchy PGO |
| **Valkey** | 9.0.0 (alpine) | Bellek içi anahtar-değer deposu (Redis uyumlu) | Uygulama önbelleği (api-a) ve global rate limit sayaçları; ACL ile kullanıcı başına anahtar öneki | Redis (8.x AGPL/SSPL), KeyDB, Dragonfly, Memcached |
| **Envoy ratelimit** | `f4e76690` | Global rate limit servisi (gRPC) | DMZ'de; partner başına dakika kotası, sayaçlar mgmt Valkey'de | Kong/Apigee/3scale kotaları, Envoy local rate limit (pod başına; o da kullanılıyor) |

## 8. Kimlik

| Bileşen | Sürüm | Amacı | Bizde nasıl kullanılıyor | Muadilleri |
|---------|-------|-------|--------------------------|------------|
| **Keycloak** | 26.8.0 (optimize build) | Kimlik sağlayıcı (OIDC/OAuth2) | mgmt `iam`: `customers`, `partners`, `staff` realm'leri; dışarıya yalnızca DMZ üzerinden OIDC uçları. Image CI'da `kc.sh build` ile optimize ([images/keycloak/Dockerfile](../images/keycloak/Dockerfile)) | Red Hat build of Keycloak (RHBK), Microsoft Entra ID, Ping Identity, ForgeRock, Okta, Auth0 |
| **auth-service** (kendi Go servisimiz) | 0.1.0 | Envoy ext_authz servisi: dış token → iç JWT | DMZ `auth`: Keycloak JWKS ile token doğrulama, kanal kuralları, RS256 iç JWT (5 dk) | oauth2-proxy, Envoy `jwt_authn` + Lua, Curity Phantom Token, API gateway eklentileri |
| **Istio ext_authz / RequestAuthentication** | Istio | Gateway'de harici yetkilendirme; JWT doğrulama | Kanal gateway'lerinde `CUSTOM` politika; cluster-a'da inline JWKS ile iç JWT doğrulama | OPA-Envoy, Authorino (Kuadrant) |

Standartlar: OAuth 2.0 (authorization code + PKCE, client credentials), OIDC, JWT (RS256), JWKS, XFCC (istemci sertifikası bilgisinin iletimi), RFC 8693 (token exchange) ve RFC 8705 (sertifikaya bağlı token) fikirleri.

## 9. Uygulamalar ve kütüphaneler

| Bileşen | Sürüm | Amacı | Bizde nasıl kullanılıyor | Muadilleri |
|---------|-------|-------|--------------------------|------------|
| **Go** | 1.27.1 | Servislerin dili | `web-bff`, `account-api`, `auth-service` ([services/](../services/)); mümkün olduğunca yalnızca standart kütüphane | Java/Spring Boot (bankalarda yaygın), Node.js, .NET, Rust |
| **distroless static** | debian12, nonroot | Minimal çalışma image'ı (kabuk ve paket yöneticisi yok) | Go servislerinin taban image'ı; UID 65532 | Chainguard/Wolfi, UBI micro (Red Hat), `scratch`, Alpine |
| **pgx** | v5.7.6 | Go için PostgreSQL sürücüsü | account-api; libpq ortam değişkenleriyle bağlantı, parametreli sorgular | `database/sql` + lib/pq, sqlx, GORM |
| **podinfo** | 6.7.1 | Örnek mikroservis (Go) | `api-a`: echo, headers, Valkey önbelleği, test uçları | httpbin, nginx, kendi servisimiz |

## 10. Sonraki adımlarda gelecekler

| Adım | Bileşen | Amacı | Muadilleri |
|------|---------|-------|------------|
| 10 · logging | **Loki** + **Fluent Bit** | Merkezi log; access log'lara `x-request-id`, kanal | ELK/OpenSearch, Splunk, Vector |
| 11 · tracing | **Grafana Tempo** + **OpenTelemetry** | Dağıtık izleme (trace) | Jaeger, Zipkin, Elastic APM |
| 13 · secrets | **HashiCorp Vault** (Community) + cert-manager + External Secrets Operator | Secret, PKI, Transit (imzalama/şifreleme), dinamik DB kimlikleri | CyberArk Conjur, AWS/Azure Secrets Manager, Sealed Secrets |
| 15 · ci | **GitHub Actions** + Trivy, gitleaks, Semgrep, Syft | İmaj/IaC taraması, secret taraması, SAST, SBOM; imzalama CI'da | GitLab CI, Jenkins, Tekton; Snyk, Grype, SonarQube |
| 16 · gitops | **Argo CD** | Cluster'ların repo'dan yönetimi | Flux, OpenShift GitOps (Argo CD) |

## 11. Lab için faydalı yardımcı araçlar

Kurulumda zorunlu değiller; incelemeyi ve hata ayıklamayı kolaylaştırırlar.

| Araç | Ne işe yarar | Örnek |
|------|--------------|-------|
| **k9s** | Terminalde Kubernetes arayüzü | `k9s --context kind-dmz` |
| **kubectx / kubens** | Context ve namespace arasında hızlı geçiş | `kubectx kind-mgmt`, `kubens iam` |
| **stern** | Birden çok pod'un logunu birlikte izleme | `stern -n istio-partner partner-gateway --context kind-dmz` |
| **Headlamp / Lens** | Masaüstü Kubernetes arayüzü | kubeconfig'teki üç context'i ekleyin |
| **istioctl analyze / proxy-config** | Istio yapılandırma hatası bulma, Envoy yapılandırmasını görme | `istioctl --context kind-dmz analyze -A`<br>`istioctl --context kind-dmz proxy-config routes deploy/partner-gateway -n istio-partner` |
| **Envoy admin** | Gateway/waypoint'in canlı yapılandırması ve sayaçları | `kubectl -n istio-partner exec deploy/partner-gateway -- pilot-agent request GET stats \| grep ratelimit` |
| **Kyverno CLI** | Politikaları cluster'a uygulamadan test etme | `kyverno apply infra/kyverno/policies.yaml --resource pod.yaml` |
| **cosign** | İmzayı elle doğrulama | `docker run --rm --network kind -v $PWD/certs/cosign:/k ghcr.io/sigstore/cosign/cosign:v2.5.3 verify --key /k/cosign.pub --allow-insecure-registry --insecure-ignore-tlog lab-registry:5000/lab/web-bff:0.2.0` |
| **crane / skopeo** | Registry'deki image'ları inceleme, kopyalama | `crane ls localhost:5001/lab/web-bff` |
| **dive** | Image katmanlarını ve boyutunu inceleme | `dive localhost:5001/lab/account-api:0.2.0` |
| **jq / yq** | JSON/YAML işleme | `kubectl get pod -o json \| jq '.items[].spec.containers[].image'` |
| **jwt-cli / jwt.io** | JWT içeriğini çözme (iç JWT'yi incelemek için) | `jwt decode <token>` (gizli token'ları çevrimiçi araçlara yapıştırmayın) |
| **step CLI** | Sertifika inceleme ve üretme | `step certificate inspect certs/partner/acme.crt` |
| **openssl s_client** | TLS el sıkışmasını ve sertifika zincirini görme | `openssl s_client -connect 127.0.0.1:8443 -servername partner-api.apps.example.local` |
| **grpcurl** | gRPC servislerini çağırma (ratelimit servisi) | `grpcurl -plaintext localhost:8081 list` (port-forward ile) |
| **hey / k6** | Yük ve hız sınırı testi | `hey -n 200 -c 20 -H "Authorization: Bearer $T" https://www.apps.example.local:8443/` |
| **pgcli / psql** | PostgreSQL'e bağlanma | `kubectl --context kind-mgmt -n data exec -it postgres-0 -- psql -U postgres -d corebank` |
| **valkey-cli** | Valkey'e bağlanma (ACL kullanıcısıyla) | `kubectl --context kind-mgmt -n data exec -it deploy/valkey -- valkey-cli --user admin --pass <parola>` |
| **Keycloak yönetim konsolu** | Realm, client ve kullanıcıları görme (dışarıya kapalı; port-forward ile) | `kubectl --context kind-mgmt -n iam port-forward svc/keycloak 8080` → http://localhost:8080/admin |
| **Trivy** | Image ve manifest güvenlik taraması | `trivy image localhost:5001/lab/auth-service:0.1.0`, `trivy config manifests/` |
| **kube-score / Polaris** | Manifest'lerde en iyi uygulama denetimi | `kube-score score manifests/dmz/*.yaml` |
