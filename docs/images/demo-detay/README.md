# Ayrıntılı demo topolojisi (lab / pilot): genelden pod içine

Bu klasör, bu makinede gerçekten çalışan demo ortamının ayrıntılı topolojisini gösterir: kind cluster'ları, Docker ağları, gerçek namespace, pod, container, port ve IP adları. Resimler büyük resimden başlar; her adımda bir katman içeri girer: Docker ağı → cluster → namespace → pod → container → node.

Hedef (prod) mimarinin aynı yapıdaki karşılığı: [prod-detay](../prod-detay/README.md). İkisi arasındaki farklar ve nedenleri: [pilot mimari dokümanı](../../pilot-architecture.md).

## Okuma sırası

| # | Resim | Ne gösterir | Seviye |
|---|-------|-------------|--------|
| 00 | [Genel bakış](00-genel-bakis.png) | Tek host, üç Docker ağı (edge-net, branch-net, kind), üç kind cluster'ı, MetalLB VIP'leri, host'a açık portlar, ana akışlar. Her blokta, ayrıntısının hangi resimde olduğunu gösteren siyah etiket | Büyük resim |
| 01 | [Docker ağları](01-docker-aglari-edge-sube.png) | edge-lb (HAProxy), edge-waf (ModSecurity), loadgen'ler, mobile-sim, branch-terminal, branch-fw, lab-registry, edge-logs: image, port, görev, ağ | Docker |
| 02 | [kind-dmz](02-dmz-cluster.png) | Kanal gateway'leri (VIP başına namespace), token handler, auth-service, ratelimit, egress gateway ve egress kuralları | Cluster |
| 03 | [DMZ pod içi](03-dmz-pod-detay.png) | mobile-gateway'in Envoy filtre zinciri, auth-service ve token handler container'ları, waypoint'ler, node agent'ları; mobil isteğin DMZ içindeki yolu | Pod |
| 04 | [kind-cluster-a](04-internal-cluster.png) | Ingress / egress gateway, BFF'ler, account-api (v1 + v2), api-a, waypoint'ler, platform; egress kuralları; açık nokta (tx-signing) | Cluster |
| 05 | [account-api pod içi](05-internal-pod-detay.png) | Waypoint'in L7 kuralları (JWT, AuthZ, canary, timeout, retry, outlier), v1 / v2 pod'ları, secret, kimlik, pod güvenlik ayarları | Pod |
| 06 | [kind-mgmt](06-mgmt-cluster.png) | Keycloak, device-registry, PostgreSQL, Valkey (önek bazlı kullanıcılar), Loki, Tempo, Prometheus, Grafana, Kiali; SNI giriş tablosu | Cluster |
| 07 | [Gözlem hattı](07-gozlem-hatti.png) | Log, metrik ve izin üreticiden ekrana yolu: fluent-bit / agent / Envoy → egress :80 → mgmt :443 → depo → Grafana, Kiali | Akış |
| 08 | [Node anatomisi](08-node-anatomisi.png) | Bir kind node'u: kontrol düzlemi, uygulama pod'ları, DaemonSet agent'ları; pod → ztunnel → HBONE → waypoint → pod; port tablosu | Node |
| 09 | [Uçtan uca istek](09-uctan-uca-mobil-transfer.png) | Mobil transferin 13 adımı: kimden → kime, port / protokol, her adımdaki kontrol | Akış |

## draw.io

Bu klasördeki resimler (00–09) tek dosyada, her biri ayrı sayfa olarak: [`demo-detay.drawio`](demo-detay.drawio). draw.io / diagrams.net'te **Dosya → Aç** (ya da **Dosya → İçe aktar → Cihaz**) ile açılır. Resim değil, draw.io bileşenleri: namespace, node ve pod'lar swimlane container (içindekiler birlikte taşınır), container ve kutuların yazısı kendi içinde, oklar bağlandığı şekle bağlı. Resimlerle aynı üreteçten çıkar: `python docs/images/src/drawio_detay.py demo-detay`.

## Nasıl okunur

Gösterim prod-detay ile aynıdır ([oradaki açıklama](../prod-detay/README.md#nasıl-okunur)); her resmin altında lejant var. Lab'e özgü olanlar:

- **Docker ağları** kalın kesikli sınırla çizilir: `edge-net` (internet tarafı), `branch-net` (şube WAN'ı), `kind` (node'lar ve VIP'ler). Ağlar arasında yalnızca `edge-waf` ve `branch-fw` köprü kurar.
- **VIP'ler** kind ağının ilk iki okteti + `.200` (dmz), `.201` (cluster-a), `.203` (mgmt) olarak yazıldı; ilk iki oktet makineye göre değişir.
- **Replika sayıları** lab değerleridir (çoğu ×1). Hedefteki sayılar prod-detay'da.
- **Kırmızı kesikli kutu / satır:** hedefte olan ama lab'de bilinçli olarak olmayan bileşen (ör. `security/tx-signing`).

## Yeniden üretme

```bash
python docs/images/src/demo_detay.py            # hepsi; ya da: python docs/images/src/demo_detay.py 03 05
E="/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"; cd docs/images/demo-detay; W=$(pwd -W)
for f in *.svg; do
  h=$(grep -o 'height="[0-9]*"' "$f" | head -1 | tr -dc 0-9)
  "$E" --headless=new --hide-scrollbars --window-size=2200,$((h + 40)) --screenshot="$W/${f%.svg}.png" "file:///$W/$f"
done
cd -; python docs/images/src/drawio_detay.py demo-detay
```

Kaynak: [`src/demo_detay.py`](../src/demo_detay.py) (resimler) ve [`src/detay_style.py`](../src/detay_style.py) (ortak yardımcılar). İçerik `manifests/`, `infra/`, `istio/values/`, `scripts/` ve `config.env` ile tutarlı tutulmalı: bir bileşen, port ya da kural değişirse ilgili resim de güncellenir.
