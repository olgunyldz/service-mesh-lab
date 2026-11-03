# 13 · Secret yönetimi: Vault, External Secrets, JWT auth, kısa ömürlü veritabanı kullanıcıları

| | |
|---|---|
| **Branch** | `secrets` (açıldığı yer: `traffic-mgmt`) |
| **Durum** | 🔄 Sıfırdan kurulum doğrulaması sürüyor |

## Amaç

Parolaları, client secret'larını ve servis kimlik bilgilerini diskteki düz dosyalardan merkezi, denetlenen bir kasaya taşımak:
- **Tek kaynak:** Her secret Vault'ta; Kubernetes Secret'ları elle değil Vault'tan otomatik oluşturuluyor.
- **En az yetki:** Her namespace yalnızca kendi secret'larını okuyabiliyor; bir cluster başka cluster'ın yolunu okuyamıyor.
- **Kısa ömür:** Servisler veritabanına kalıcı parolayla değil, Vault'un ürettiği 1 saatlik kullanıcıyla bağlanıyor.
- **Denetim:** Kim hangi secret'ı ne zaman okudu, merkezi logda (Loki, security).

Ek olarak (bu adımda bulunan açık): edge container'ları node'lara ve registry'ye ulaşabiliyordu; kapatıldı.

Hedefteki karşılığı: IAM ve SOC bölümlerindeki secret / anahtar yönetimi maddeleri ([hedef mimari](target-architecture.md)). PKI (Istio CA'nın Vault'a taşınması) ayrı adım: `13a · pki`.

## Adım sonundaki durum

| Konu | Durum |
|------|-------|
| Vault | mgmt'te (`ns vault`), HashiCorp Vault Community 2.1, tek pod, Raft depolama, ambient mesh içinde. Başlatma ve mühür açma kurulum script'inde (`05b-setup-vault.sh`) |
| Secret'lar | 39 parola ve client secret'ı `kv/ops/passwords`'te; uygulama secret'ları `kv/<cluster>/<namespace>/<ad>` yollarında. **`certs/data/*.pw` düz dosyaları kalktı** |
| Kubernetes Secret'ları | External Secrets Operator (her cluster'da, yalnızca controller) Vault'tan oluşturuyor; Secret'ların sahibi `ExternalSecret`. Secret adları ve anahtarları değişmedi |
| Kimlik doğrulama | Cluster başına JWT auth (`jwt-dmz`, `jwt-cluster-a`, `jwt-mgmt`). Vault cluster API'sini çağırmıyor: service account token'larının imza anahtarı ve issuer sabit olarak yazılı |
| Yetki | Namespace başına politika (`<cluster>-<namespace>`: yalnızca kendi KV yolu) ve rol (yalnızca o namespace'in `vault-reader` service account'u) |
| Veritabanı | account-api ve device-registry Vault Database motorunun ürettiği **1 saatlik PostgreSQL kullanıcısıyla** bağlanıyor; 30 dk'da bir yenileniyor. `account_api` / `device_registry` artık giriş yapamayan roller (NOLOGIN). Süresi dolan ya da iptal edilen kullanıcının açık oturumları kapatılıp rolü siliniyor |
| Ağ yolu | dmz / cluster-a → `external-secrets` namespace'inin waypoint'i → egress gateway → mgmt girişi (`vault.mgmt.internal`) → Vault. Her geçişte kaynak kimliği ve yol kuralı |
| Audit | Vault audit logu stdout → Fluent Bit → Loki (`security` kategorisi); hassas değerler HMAC'li |
| Edge izolasyonu | Node'larda API sunucusu, kubelet ve NodePort'lar yalnızca host, node'lar ve node'un pod'ları için (`guard_nodes`). Registry'ler ayrı Docker ağında (`registry-net`) |
| Kaynak | Vault ~100 MB, External Secrets cluster başına ~80 MB, 2 waypoint. Bellek sınırı nedeniyle External Secrets'ın cluster genelindeki CRD'leri kurulmuyor, `LOADGEN_INTERVAL` 5 → 10 sn |

## Önceki adıma göre değişenler

| Değişiklik | Neden |
|------------|-------|
| **Yeni** `infra/vault/vault.yaml` | Vault: namespace, StatefulSet (Raft, PVC), Service'ler, varsayılan-reddet + yalnızca mgmt ingress gateway'i ve mgmt External Secrets'ı |
| **Yeni** `scripts/05b-setup-vault.sh` (eski `05b-create-data-secrets.sh` yerine) | Vault kurulumu, init / unseal, audit, KV, JWT auth, politika ve roller; External Secrets kurulumu; parolaların ve uygulama secret'larının Vault'a yazılması. Önceki kurulumun `certs/data`'sı varsa değerler bir kez taşınıp dosyalar silinir |
| **Yeni** `scripts/06a-vault-database.sh` | Database motoru (PostgreSQL ayağa kalktıktan sonra): `vault_admin` bağlantısı, parolasının döndürülmesi, `account-api` ve `device-registry` rolleri; Valkey hazır olunca api-a'nın bir kez yeniden başlatılması |
| **Yeni** `manifests/<cluster>/01-secrets.yaml` | Namespace başına `vault-reader` SA, `SecretStore`, `ExternalSecret`'lar; veritabanı kullanıcısı için `VaultDynamicSecret` üreteci |
| **Yeni** `manifests/{dmz,cluster-a}/64-vault-exit.yaml` | `external-secrets` namespace'inin waypoint'i ve Vault çıkışı (egress, yalnızca bu cluster'ın yolları) |
| **Yeni** `manifests/mgmt/37-vault-entry.yaml` | mgmt girişi: `vault.mgmt.internal`, kaynak egress kimliğine göre yol kuralı |
| `manifests/mgmt/20-data.yaml` | `account_api`, `device_registry` NOLOGIN; `vault_admin` (CREATEROLE, iki role yalnızca üyelik verebilir, `pg_signal_backend`); Vault'un postgres'e erişimi |
| account-api 0.5.2, device-registry 0.1.1 | Kullanıcı adı ve parola dosyadan, her yeni bağlantıda (`DB_CREDENTIALS_DIR`); bağlantı ömrü 10 dk. Pod yeniden başlamadan yeni kullanıcıya geçer |
| `15/17-account-api.yaml`, `32-device-registry.yaml` | `envFrom` yerine Secret dosya olarak bağlı |
| `scripts/lib.sh` | `vault_cmd`, `pwf` (parolalar Vault'tan); registry ağı (`registry_network`); `guard_nodes` |
| `06b`, `06c`, `07b`, `08-verify.sh` | Parolalar `pwf` ile Vault'tan; "17) Secret yönetimi" ve "18) Edge izolasyonu" testleri |
| `infra/logging/fluent-bit.yaml` | `vault` namespace'i → `security` kategorisi |
| `01-create-clusters.sh`, `03b-publish-images.sh`, `config.env` | Registry'ler `registry-net`'te, node koruması; Vault ve External Secrets image'ları (imzalı, lab registry); `LOADGEN_INTERVAL=10` |

## Eklenen bileşenler

| Bileşen | Amaç | Neden bu | Muadilleri |
|---------|------|----------|------------|
| **HashiCorp Vault Community 2.1** | Secret, dinamik kimlik bilgisi ve (13a'da) PKI için tek kasa | Gerçek ortamla config, politika ve komutlar birebir aynı; Database, PKI, Transit motorları tek üründe. Lisans BSL 1.1 (iç kullanım ücretsiz) | OpenBao (Vault'un açık kaynak çatalı), CyberArk Conjur, AWS Secrets Manager / Azure Key Vault / GCP Secret Manager, Thycotic / Delinea |
| **External Secrets Operator 2.13** | Vault'taki değerleri Kubernetes Secret'ına çevirmek; yenilemek | Uygulama Vault'u bilmiyor (Secret okumaya devam); namespace'e bağlı SecretStore ile en az yetki; dinamik kimlik bilgisi üreteci var | Vault Agent Injector (sidecar), Vault Secrets Operator (HashiCorp), Secrets Store CSI Driver, Sealed Secrets / SOPS (GitOps, kasa değil) |
| **Vault JWT auth** | Cluster'ların Vault'a kimlik doğrulaması | Vault'un cluster API'lerini çağırması gerekmez (Kubernetes auth'ta TokenReview çağrısı gerekir): zone izolasyonu korunur | Kubernetes auth, AppRole, OIDC (cluster'ın OIDC discovery'si ile) |
| **Vault Database motoru (PostgreSQL)** | Servis başına kısa ömürlü veritabanı kullanıcısı | Sızan parola en fazla 1 saat geçerli; servis başına ayrı kullanıcı, her giriş Vault'ta kayıtlı | Statik rol + periyodik döndürme (Vault), CyberArk, CloudNativePG'nin rol yönetimi, IAM veritabanı kimlik doğrulaması (bulut) |

## Tasarım kararları

- **JWT auth, Kubernetes auth değil.** Kubernetes auth'ta Vault her girişte cluster'ın API sunucusuna TokenReview gönderir: mgmt'ten DMZ'ye yol açmak gerekirdi. JWT auth'ta Vault yalnızca imzayı doğrular (sabit açık anahtar). Bedeli: cluster'ın service account imza anahtarı değişirse Vault'taki anahtar da güncellenmeli.
- **Namespace başına SecretStore, ClusterSecretStore yok.** Cluster genelindeki store, her namespace'in herkesin secret'ını isteyebilmesi demek. Namespace başına store + rol + politika: bir namespace başka namespace'in yolunu okuyamaz (test). Cluster genelindeki CRD'ler hiç kurulmuyor (bellek de kazanılıyor).
- **Zone geçişinde kimlik.** External Secrets → Vault isteği önce namespace'in waypoint'inden geçer: egress gateway kaynağı yalnızca bu waypoint'in kimliğiyle kabul eder, mgmt girişi egress'in kimliğine göre yalnızca o cluster'ın yollarını açar (`dmz` → `kv/data/dmz/*`). Vault'un yönetim API'si (`sys/`) dışarıdan kapalı.
- **Veritabanı kullanıcısında batch token.** Vault, iptal edilen token'ın aldığı kiraları (lease) da iptal eder. External Secrets işi bitince token'ını iptal ettiğinde, aldığı veritabanı kullanıcısı da silinirdi (sorun 3). Veritabanı rolleri batch token alır: kiraları token'a bağlı değildir, kendi ömürleriyle (1 sa) yaşar; token 2 sa sonra kendiliğinden biter.
- **İptal oturumu da kapatır.** PostgreSQL bir rol silinince açık oturumlara dokunmaz; kısa ömür kâğıt üzerinde kalırdı. Vault'un iptal ifadesi önce oturumları kapatır (`pg_terminate_backend`), sonra rolü siler. Servis yeni bağlantıyı dosyadaki yeni kullanıcıyla açar (test: eski kullanıcı iptal edildi, istek 200, pod yeniden başlamadı).
- **Uygulama Vault'u bilmiyor.** Servis Secret'ı dosya olarak okur; Vault SDK'sı yok. Başka bir kasaya geçişte uygulama değişmez.
- **Keycloak statik kullanıcıyla.** Keycloak'ın bağlantı havuzu parolayı açılışta okur; dinamik kullanıcı için her yenilemede yeniden başlatma gerekirdi. Parolası Vault'ta, döndürme elle (13a sonrası değerlendirilecek).
- **Edge izolasyonu ağ katmanında.** kind ağı düz bir Docker ağı: edge container'ları gateway VIP'lerine ulaşabilsin diye bu ağda, ama aynı ağda node'ların yönetim portları da var. Node'larda bu portlar yalnızca host, node'lar ve pod'lar için açık; registry'ler ayrı ağda.

## STRIDE (yeni ve değişen akışlar)

| Akış | Tehdit | Senaryo | Kontrol | Durum |
|------|--------|---------|---------|-------|
| Secret okuma | **I**nformation disclosure | Bir namespace başka namespace'in / cluster'ın secret'ını okur | Namespace başına rol + politika; JWT mount cluster başına (test) | ✅ |
| | **S**poofing | Başka namespace'in service account token'ıyla giriş | Rol yalnızca `system:serviceaccount:<ns>:vault-reader` (test) | ✅ |
| | **S**poofing | Bir cluster'ın token'ı başka cluster'ın mount'unda | Mount'ta yalnızca o cluster'ın imza anahtarı (test) | ✅ |
| Vault'a ağ yolu | **E**levation of privilege | DMZ'den Vault yönetim API'si (`sys/`) ya da başka cluster'ın yolu | Egress: yalnızca waypoint kimliği + bu cluster'ın yolları; mgmt girişi: egress kimliği + yol (test) | ✅ |
| Parola deposu | **I**nformation disclosure | Diskteki düz parola dosyaları | `certs/data` kalktı; parolalar Vault'ta (test) | ✅ |
| | **I**nformation disclosure | Vault root token / unseal anahtarı diskte (`certs/vault/init.json`) | Lab istisnası; gerçekte HSM / KMS ile otomatik unseal, root token kurulumdan sonra iptal | ⚠️ Lab |
| Veritabanı | **I**nformation disclosure | Sızan servis parolası süresiz geçerli | 1 saatlik kullanıcı; statik servis kullanıcısı yok (NOLOGIN, test) | ✅ |
| | **R**epudiation | Hangi servis kopyası bağlandı bilinmiyor | Her kullanıcı Vault kirasıyla ilişkili; Vault audit logu Loki'de (test) | ✅ |
| | **E**levation of privilege | Vault'un veritabanı yöneticisi her şeyi yapabilir | `vault_admin` yalnızca kullanıcı üretir ve iki role üyelik verir; rollerin yetkisini kendisi kullanamaz; ilk parolası geçersiz (test) | ✅ |
| Edge | **E**levation of privilege | Ele geçirilen edge-waf / branch-fw'den Grafana, Kiali (anonim), API sunucusu, kubelet | Node koruması (test) | ✅ |
| | **T**ampering | Edge'den kimliksiz lab registry'ye image itmek | Registry ayrı ağda (test); imzasız image zaten Kyverno'da reddedilir | ✅ |

## Karşılaşılan sorunlar ve çözümler

| # | Sorun | Neden | Çözüm |
|---|-------|-------|-------|
| 1 | External Secrets'ın Vault isteği egress'te reddedildi (`rbac_access_denied`) | Ambient pod'dan egress gateway'e (mesh dışı gateway pod'u) giden düz HTTP'de kaynak kimliği yok | Diğer çıkışlardaki desen: `external-secrets` namespace'ine waypoint; egress waypoint'in kimliğini mTLS ile görür |
| 2 | Vault girişinden sonra istekler 403 | External Secrets girişten sonra token'ını doğrular (`lookup-self`) ve işi bitince iptal eder (`revoke-self`); yol kurallarında yoktu | İki yol da izinli (yalnızca kendi token'ı) |
| 3 | account-api ve device-registry birkaç dakika sonra veritabanına bağlanamadı (`password authentication failed`) | Vault, iptal edilen token'ın kiralarını da iptal eder: External Secrets token'ını bırakınca veritabanı kullanıcısı silindi | Veritabanı rollerinde batch token (kiralar token'a bağlı değil) |
| 4 | Canlı denemede makinenin belleği bitti, Docker Desktop yanıt vermedi | Vault, 3 External Secrets, 2 waypoint ve External Secrets'ın büyük CRD'leri (ClusterSecretStore tek başına ~0,7 MB şema) | External Secrets'ın cluster genelindeki CRD'leri kurulmuyor; `LOADGEN_INTERVAL` 10 sn (kullanıcı kararı: WSL 12 GB'ta kalır) |
| 5 | api-a önbelleği "offline" | Secret'lar External Secrets'la geldiği için api-a Valkey'den önce açılabiliyor; podinfo önbelleğe yalnızca açılışta bağlanıyor | `06a`: Valkey hazır olunca api-a bir kez yeniden başlatılır |
| 6 | Kurulum script'i sessizce durdu | `[[ -n $db ]] && ...` satırı, `pipefail` + `set -e` altında grubun çıkış kodunu 1 yaptı | `if` ile |
| 7 | `helm` değer dosyasını bulamadı | Windows `helm.exe` `/tmp/...` yolunu görmüyor | `cygpath -m` |
| 8 | Edge container'ları Grafana, Kiali (anonim), Keycloak yönetimi NodePort'larına, API sunucusuna, kubelet'e ve registry'ye ulaşabiliyordu | kind ağı düz bir Docker ağı; NodePort'lar node adresinde herkese açık | Node koruması (`guard_nodes`, raw tablosu); registry'ler `registry-net`'te. Lab registry ağ değişince yeniden başlatılmalı (yayınlanan port düşüyor) |

## Doğrulama

Sıfırdan kurulum (`99-destroy.sh` → `setup.sh`, `08-verify.sh` dahil) sürüyor; sonuç eklenecek. Önceki sıfırdan kurulumda bulunan sorunlar (3, 5) düzeltildi ve canlı ortamda doğrulandı.

Bu adımda eklenen testler (`08-verify.sh` → "17) Secret yönetimi", "18) Edge izolasyonu"):

| Test | Beklenen | Sonuç |
|------|----------|-------|
| Vault başlatılmış, mührü açık; diskte düz parola yok | – | ⏳ |
| Her cluster'da tüm ExternalSecret'lar senkron; Secret'ın sahibi ExternalSecret | – | ⏳ |
| JWT auth: kendi yolu okunuyor; başka namespace / cluster / parola deposu okunamıyor | `permission denied` | ⏳ |
| JWT auth: başka namespace'in token'ı ve başka cluster'ın token'ı giriş yapamıyor | hata | ⏳ |
| DMZ: Vault çıkışı External Secrets dışındaki pod'a kapalı | 403 | ⏳ |
| Veritabanı: Vault kullanıcısı (`v-…`), statik servis kullanıcıları NOLOGIN, `vault_admin`'in ilk parolası geçersiz | – | ⏳ |
| Yenileme: yeni kullanıcı; eski kullanıcı iptal → rol ve oturum yok; account-api 200, pod yeniden başlamadı; logda yeni kullanıcı | – | ⏳ |
| Vault audit logu Loki'de (security); Vault ve External Secrets imzalı image | – | ⏳ |
| edge-waf, branch-fw, edge-logs: node portları ve registry'ye ulaşamıyor; node koruması her node'da; registry'ler kind ağında değil | `000` | ⏳ |

## Bilinen kısıtlar

- **Unseal elle, anahtar diskte.** `certs/vault/init.json` (unseal anahtarı + root token) gitignore'lu ama diskte; tek anahtar parçası. Gerçekte HSM / bulut KMS ile otomatik unseal, Shamir parçaları ayrı kişilerde, root token kurulumdan sonra iptal. Vault pod'u yeniden başlarsa mühürlü açılır; `05b-setup-vault.sh` yeniden çalıştırılarak açılır.
- **Tek node Raft.** Gerçekte 3 / 5 node, DC'ler arası replikasyon (Enterprise) ya da DR planı.
- **Vault dinleyicisi düz HTTP.** Taşıma şifrelemesi ve kimlik mesh'te (ztunnel mTLS); Vault'un kendi TLS'i `13a · pki` ile.
- **Statik secret'lar döndürülmüyor.** Keycloak client secret'ları, Valkey ACL parolaları, test kullanıcıları Vault'ta ama otomatik döndürme yok.
- **Istio ve zone CA anahtarları hâlâ diskte** (`certs/`): `13a · pki`.
- **Node koruması kalıcı değil.** Node container'ı yeniden başlarsa iptables kuralı kaybolur (Docker Desktop yeniden başlatma); `08-verify.sh` yakalar, `guard_nodes` yeniden uygular.
- **Transit (alan şifreleme, PAN tokenizasyonu)** `14 · pci-zone` ile.
