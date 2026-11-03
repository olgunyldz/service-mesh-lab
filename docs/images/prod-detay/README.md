# Ayrıntılı prod topolojisi (hedef mimari): genelden pod içine

Bu klasör [hedef mimarinin](../../target-architecture.md) ayrıntılı topolojisini (`topology-prod-full-wss-ai`) parçalara ayırır. Resimler büyük resimden başlar; her adımda bir katman içeri girer: zone → cluster → namespace → pod → container → node.

## Okuma sırası

| # | Resim | Ne gösterir | Seviye |
|---|-------|-------------|--------|
| 00 | [Genel bakış](00-genel-bakis.png) | Tüm kanallar, zone'lar, cluster'lar, güven sınırları ve ana akışlar. Her blokta, ayrıntısının hangi resimde olduğunu gösteren siyah etiket | Büyük resim |
| 01 | [Giriş katmanı](01-giris-edge-sube-atm.png) | İnternet edge (DDoS → GSLB → NGFW → F5 / WAF) ve F5 VIP tablosu; şube ağı; ATM / POS. Kubernetes dışı cihazlar | Zone |
| 02 | [DMZ cluster'ı](02-dmz-cluster.png) | ocp-dmz: infra ve worker node havuzları, namespace'ler, pod'lar (replika, görev) | Cluster |
| 03 | [DMZ pod içi](03-dmz-pod-detay.png) | Gateway'in Envoy filtre zinciri, auth-proxy ve token handler container'ları, waypoint, node agent'ları; mobil isteğin DMZ içindeki yolu | Pod |
| 04 | [Internal cluster'ı](04-internal-cluster.png) | ocp-apps: giriş / çıkış gateway'leri, channel-bff, on domain namespace'i ve waypoint'leri, platform bileşenleri | Cluster |
| 05 | [Internal pod içi](05-internal-pod-detay.png) | Ödeme (transfer) pod'u: container, secret, kimlik, waypoint'in L7 kuralları, çağırdığı servisler ve port'lar; pod güvenlik ayarları | Pod |
| 06 | [Veri, core, PCI](06-veri-core-pci.png) | ocp-data (PostgreSQL, Kafka, Valkey, RabbitMQ StatefulSet'leri, VM'ler), ocp-core, ocp-pci (switch'ler, tokenization, HSM) | Cluster |
| 07 | [Kimlik ve yönetim](07-kimlik-yonetim.png) | ocp-iam (Keycloak StatefulSet'i, yardımcı servisler, HSM), ocp-mgmt (log / metrik / iz hattı, Vault, Harbor, Argo CD) | Cluster |
| 08 | [Node anatomisi](08-node-anatomisi.png) | Bir node'daki pod'lar ve DaemonSet agent'ları (ztunnel, istio-cni, fluent-bit…); bir isteğin pod → ztunnel → HBONE → waypoint → pod yolu; port tablosu | Node |
| 09 | [Uçtan uca istek](09-uctan-uca-mobil-transfer.png) | Mobil transferin 15 adımı: kimden → kime, port / protokol, her adımdaki kontrol | Akış |

## draw.io

Bu klasördeki resimler (00–09) tek dosyada, her biri ayrı sayfa olarak: [`prod-detay.drawio`](prod-detay.drawio). draw.io / diagrams.net'te **Dosya → Aç** (ya da **Dosya → İçe aktar → Cihaz**) ile açılır. Resim değil, draw.io bileşenleri: namespace, node ve pod'lar swimlane container (içindekiler birlikte taşınır), container ve kutuların yazısı kendi içinde, oklar bağlandığı şekle bağlı. Resimlerle aynı üreteçten çıkar: `python docs/images/src/drawio_detay.py prod-detay`.

## Nasıl okunur

Gösterim her resimde aynıdır ve her resmin altında bir lejant bulunur:

- **Renk = güven seviyesi (zone):**
  - kırmızımsı: internet,
  - sarı: edge,
  - turuncu: DMZ,
  - mavi: internal,
  - yeşil-mavi: kimlik,
  - mor: veri,
  - koyu kırmızı: PCI,
  - yeşil: yönetim.
- **Kalın kesikli çizgi:** güven sınırı (internet, kurum WAN, banka perimetresi, private zone, PCI).
- **İnce kesikli çerçeve:** namespace. **Koyu düz çerçeve:** node.
- **Pod kutusu:** sağ üstte iş yükü türü ve replika sayısı. Kesikli kenarlı pod DaemonSet'tir, yani her node'da birer tane çalışır.
- **Pod içindeki renkli kutular container'lardır:**
  - mavi: uygulama,
  - turuncu: Envoy proxy,
  - yeşil: agent,
  - mor: veri / secret,
  - gri kesikli: kimlik / init.
- **Rozetler:**
  - **⇥ yeşil:** giriş. Kimden, hangi port ve protokolle gelinir.
  - **↦ turuncu:** çıkış. Nereye, hangi port ve protokolle gidilir.
- **Oklar:**
  - **Mavi kalın:** mTLS ana akış.
  - **Gri:** istek / bağlantı.
  - **Gri kesikli:** yardımcı akış (log, metrik, kontrol, yanıt).
  - **Kırmızı kesikli:** olmayan / yasak yol.
- **Numaralı daireler:** adımlar (03, 05, 08, 09) ya da ayrıntı resmi (00'daki siyah etiketler).

## Kapsam

Resimler **hedef (prod) mimariyi** gösterir: 2 DC, OpenShift, Istio ambient, WSS ve kontrollü on-prem AI. Lab'deki (pilot) karşılıkları ve farklar [pilot mimari dokümanında](../../pilot-architecture.md); örneğin pilotta log için Loki, gözlem için Prometheus ve Tempo kullanılıyor.

## Yeniden üretme

```bash
python docs/images/src/prod_detay.py            # hepsi; ya da: python docs/images/src/prod_detay.py 03 05
E="/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"; cd docs/images/prod-detay; W=$(pwd -W)
for f in *.svg; do
  h=$(grep -o 'height="[0-9]*"' "$f" | head -1 | tr -dc 0-9)
  "$E" --headless=new --hide-scrollbars --window-size=2200,$((h + 40)) --screenshot="$W/${f%.svg}.png" "file:///$W/$f"
done
```

Kaynak: [`src/prod_detay.py`](../src/prod_detay.py) (resimler) ve [`src/detay_style.py`](../src/detay_style.py) (namespace, node, pod, container, rozet, lejant yardımcıları). İçerik [`src/topo_prod_full.py`](../src/topo_prod_full.py) ve hedef mimari dokümanıyla tutarlı tutulmalı.
