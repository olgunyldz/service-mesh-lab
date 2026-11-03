# Topoloji diyagramları

Bu klasördeki üreteçler (yalnızca Python standart kütüphanesi):

| Üreteç | Çıktı |
|---|---|
| `topo_lab.py` | `../topology-lab.svg`: lab, mevcut durum |
| `topo_prod.py` | `../topology-prod.svg`: gerçek banka ortamı (prod, hedef) |
| `topo_prod_full.py` | `../topology-prod-full.svg`: ayrıntılı prod (kanal → zone → cluster → domain → veri → dış çıkış; güven sınırları, renkli), 2630 px |
| `zone_images.py` | `../zone-{edge,dmz,sube,kimlik,internal}.svg`: zone iç yapısı + kontroller + lab karşılığı |
| `zone_ozet.py` | `../zone-ozet.svg`: özet zone mimarisi (güven kademeleri, kanalların giriş yolu), 1560 px |
| `topo_style.py` | ortak stil ve çizim yardımcıları |
| `prod_detay.py` + `detay_style.py` | `../prod-detay/NN-*.svg`: hedef mimarinin ayrıntılı seti (genel bakış → cluster → pod → node → uçtan uca akış); bkz. [prod-detay/README.md](../prod-detay/README.md) |
| `demo_detay.py` + `detay_style.py` | `../demo-detay/NN-*.svg`: bu makinedeki demo (lab) ortamının aynı yapıdaki seti (Docker ağları, kind cluster'ları, gerçek adlar ve portlar); bkz. [demo-detay/README.md](../demo-detay/README.md) |
| `drawio_detay.py` | `../<set>/<set>.drawio`: ayrıntı setini (prod-detay, demo-detay) aynı resim fonksiyonlarından draw.io bileşenleriyle üretir: resim başına sayfa; namespace / node / pod container, oklar şekillere bağlı; `python docs/images/src/drawio_detay.py [prod-detay] [demo-detay]` |
Stil `../detayli-topoloji.png` ile uyumludur: dikey akış, kesikli zone kutuları, mavi = ana mTLS akışı, kesikli = planlı.

```bash
python docs/images/src/topo_lab.py
python docs/images/src/topo_prod.py
python docs/images/src/zone_images.py
python docs/images/src/topo_prod_full.py
python docs/images/src/zone_ozet.py

# PNG (Windows, headless Edge):
E="/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"; cd docs/images; W=$(pwd -W)
"$E" --headless=new --hide-scrollbars --window-size=1340,1800 --screenshot="$W/topology-lab.png"  "file:///$W/topology-lab.svg"
"$E" --headless=new --hide-scrollbars --window-size=1340,2170 --screenshot="$W/topology-prod.png" "file:///$W/topology-prod.svg"
"$E" --headless=new --hide-scrollbars --window-size=2630,3175 --screenshot="$W/topology-prod-full.png" "file:///$W/topology-prod-full.svg"
"$E" --headless=new --hide-scrollbars --window-size=1560,1610 --screenshot="$W/zone-ozet.png" "file:///$W/zone-ozet.svg"
for f in zone-edge zone-dmz zone-sube zone-kimlik zone-internal; do   # yükseklik SVG'den
  h=$(grep -o 'height="[0-9]*"' $f.svg | head -1 | tr -dc 0-9)
  "$E" --headless=new --hide-scrollbars --window-size=1340,$h --screenshot="$W/$f.png" "file:///$W/$f.svg"
done
```
