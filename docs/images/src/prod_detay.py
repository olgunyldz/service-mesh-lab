"""Ayrıntılı prod topolojisi seti (hedef mimari, WSS + AI): genelden pod içine kadar.
Çıktı: docs/images/prod-detay/NN-*.svg (PNG için prod-detay/README.md'deki komut).
Çalıştırma: python docs/images/src/prod_detay.py [resim numaraları...]   (boş: hepsi)
Kaynak: topo_prod_full.py (topology-prod-full-wss-ai) ve docs/target-architecture.md."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from detay_style import D

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "prod-detay")
os.makedirs(OUT, exist_ok=True)

ZONES_ALL = [("public", "internet"), ("wan", "kurum WAN"), ("edge", "edge"), ("dmz", "DMZ"), ("internal", "internal"),
             ("identity", "kimlik"), ("pci", "PCI"), ("core", "core banking"), ("data", "veri"), ("egress", "dış çıkış"),
             ("mgmt", "yönetim / gözlem"), ("external", "dış dünya")]


def out(name):
    return os.path.join(OUT, name)


# =====================================================================================================================
def img00():
    W, H, OY = 2200, 1590, 40
    d = D(W, H)
    # Güven sınırları
    d.boundary([(20, 90), (1316, 90), (1316, 200), (20, 200)], "İNTERNET · GÜVENİLMEYEN", "public", fill_opacity=0.5)
    d.boundary([(1324, 90), (1836, 90), (1836, 200), (1324, 200)], "KURUM WAN · ÖZEL AĞ", "wan", fill_opacity=0.6)
    d.boundary([(14, 216), (1846, 216), (1846, 1250), (14, 1250)], "BANKA PERİMETRESİ", "external")
    d.boundary([(26, 640), (1834, 640), (1834, 1240), (26, 1240)], "PRIVATE ZONE · İNTERNETE KAPALI", "internal", label_at=(1460, 624))
    d.boundary([(1330, 410), (1828, 410), (1828, 612), (1330, 612)], "PCI DSS", "pci", label_at=(1350, 396))
    d.boundary([(1866, 400), (2180, 400), (2180, 980), (1866, 980)], "DIŞ DÜNYA", "external", fill_opacity=0.6)

    # Kanallar
    for i, (t, s) in enumerate([("Web", "tarayıcı · ib"), ("Mobil uygulama", "m-api · WSS"), ("Partner / TPP", "api · mTLS")]):
        d.channel(40 + i * 425, 112, 405, t, s, h=70)
    for i, (t, s) in enumerate([("Şube", "SD-WAN"), ("ATM", "özel ağ"), ("POS", "APN")]):
        d.channel(1340 + i * 164, 112, 150, t, s, h=70)

    # Edge
    d.zone(40, 236, 1260, 150, "Internet Edge (DC1 / DC2) · cluster dışı cihazlar", color="edge", title_above=True)
    for i, (t, s) in enumerate([("DDoS koruma", "scrubbing · anycast"), ("GSLB / DNS", "DC1 ⇄ DC2"), ("Perimeter NGFW", "yalnızca 443/TCP"),
                                ("F5 LTM + WAF", "TLS 1.3 · VIP · WAF")]):
        x = 64 + i * 305
        d.box(x, 290, 280, 72, t, [s], color="edge")
        if i < 3:
            d.flow([(x + 280, 326), (x + 305, 326)], "req")
    d.link(1150, 262, "Ayrıntı: 01")
    d.zone(1340, 236, 230, 150, "Şube zone", ["branch-fw · branch-gw", "NAC · cihaz sertifikası"], color="wan")
    d.zone(1586, 236, 234, 150, "ATM · POS ağı", ["atm-fw · pos-fw · APN", "ISO 8583 · NDC (TLS)"], color="wan")
    d.link(1452, 374, "01")
    d.link(1700, 374, "01")

    d.firewall(40, 396, 1260, 20, "İÇ FIREWALL (farklı üretici) · yalnızca F5 → DMZ :443", tx=420)
    # DMZ
    d.zone(40, 426, 1260, 186, "DMZ · ocp-dmz (DC1 / DC2) · iş mantığı yok", color="dmz", title_above=True)
    for i, (t, ls) in enumerate([("dmz-egressgw", ["internal'a TEK kapı", "dış token silinir"]),
                                 ("auth-proxy (ext_authz)", ["introspection · token exchange", "→ iç JWT (≤ 2 dk)"]),
                                 ("web-token-handler", ["cookie ↔ token · CSRF", "WSS: kısa ömürlü bilet"]),
                                 ("Kanal gateway'leri", ["web · mobil · partner", "TLS sonlandırma · kota"])]):
        d.box(64 + i * 305, 480, 280, 96, t, ls, color="dmz")
    d.flow([(979, 528), (954, 528)], "req")
    d.flow([(674, 528), (649, 528)], "req")
    d.flow([(369, 528), (344, 528)], "req")
    d.flow([(1123 + 40, 576), (1123 + 40, 596), (518, 596), (518, 576)], "aux", "ext_authz", 760, 592)
    d.link(1086, 452, "Ayrıntı: 02 · 03")
    # PCI
    d.zone(1340, 426, 480, 176, "Kart zone · ocp-pci (ayrı cluster)", ["atm-switch · pos-switch · iso8583-adapter", "tokenization · HSM (payShield)",
                                                                      "yalnızca token PAN internal'a çıkar"], color="pci")
    d.link(1736, 588, "06")

    d.firewall(40, 618, 1260, 18, "INTERNAL FIREWALL · yalnızca gateway'ler → int-ingressgw :443", tx=380)
    # Internal
    d.zone(40, 656, 1260, 248, "Internal · ocp-apps A / B (DC1 / DC2) · domain bazlı namespace · Istio ambient", color="internal", title_above=True)
    d.box(64, 708, 1212, 50, "int-ingressgw → channel-bff (web · mobil · şube BFF, realtime-gw)", [], color="internal", size=13)
    doms = ["hesap", "ödeme", "kart", "kredi", "müşteri", "bildirim", "entegrasyon", "security · AI", "raporlama", "olay (Kafka)"]
    for i, t in enumerate(doms):
        x = 64 + (i % 5) * 244
        y = 772 + (i // 5) * 52
        d.box(x, y, 228, 42, "ns " + t, [], color="internal", size=12)
    d.text(64, 892, "her ns: waypoint (L7 yetki: scope · acr · rol · sahiplik) · ztunnel (mTLS, L4) · int-egressgw (tek çıkış)", 12.5, 400, "#2b2b2b")
    d.link(1100, 682, "Ayrıntı: 04 · 05")
    # Kimlik, dış çıkış
    d.zone(1340, 656, 480, 118, "Kimlik zone · ocp-iam A / B", ["Keycloak (müşteri · partner · personel)", "device-registry · consent · HSM"], color="identity")
    d.link(1736, 760, "07")
    d.zone(1340, 788, 480, 116, "Dış çıkış zone", ["outbound NGFW · forward proxy", "VPN / kiralık hat · SMTP · SMS"], color="egress")

    # Core, data, ambar
    d.zone(40, 926, 600, 150, "Core banking · ocp-core / VM", ["core-ingressgw (yalnızca core-adapter)", "ledger · EOD batch · IBM MQ"], color="core")
    d.link(560, 1062, "06")
    d.zone(660, 926, 640, 150, "Data zone · ocp-data + VM", ["PostgreSQL (CNPG) · Kafka · Valkey · RabbitMQ", "Oracle RAC · MSSQL AG · nesne depolama"], color="data")
    d.link(1220, 1062, "06")
    d.zone(1340, 926, 480, 150, "Veri ambarı · AI veri hattı", ["CDC · ETL · feature store", "model registry · maskeli veri"], color="data")
    d.link(1736, 1062, "06")
    # Mgmt
    d.zone(40, 1098, 1780, 134, "Yönetim ve gözlem · ocp-mgmt (DC1 / DC2)",
           ["log · metrik · iz (tek yönlü, yalnızca yazma) · SIEM · WORM", "Vault / PKI · Harbor · GitOps · bastion / PAM"], color="mgmt")
    d.link(1736, 1218, "07")

    # Dış dünya
    d.box(1886, 440, 276, 84, "Kart şemaları", ["Visa · Mastercard · TROY", "BKM"], color="external")
    d.box(1886, 680, 276, 84, "Dış kurumlar", ["EFT / FAST · SWIFT", "KKB · MERNİS"], color="external")
    d.box(1886, 810, 276, 84, "İnternet servisleri", ["SMS · push · e-posta", "SaaS"], color="external")

    # Akışlar
    for i in range(3):
        x = 40 + i * 425 + 202
        d.flow([(x, 182), (x, 290 if i < 3 else 236)], "req")
    d.badge(260, 230, "in :443 HTTPS / WSS (TLS 1.3)", "in")
    d.flow([(1123 + 140, 362), (1123 + 140, 480)], "main", ":443 mTLS", 1123 + 132, 452, "end")
    for x in (1405, 1569, 1733):
        d.flow([(x, 182), (x, 236)], "req")
    d.flow([(1760, 386), (1760, 426)], "main", "TLS", 1768, 420)
    # DMZ -> internal
    d.flow([(160, 576), (160, 708)], "main", "mTLS :443 + iç JWT (IdP)", 172, 598)
    d.badge(1268, 742, "in :443 yalnızca gateway kimlikleri", "in", anchor="end")
    # şube -> internal
    d.flow([(1400, 386), (1400, 402), (1322, 402), (1322, 733), (1276, 733)], "main")
    d.vt(1316, 520, "şube: mTLS + iç JWT", 12, "#1f1f1f", 600)
    # pci <-> internal (kart ns)
    d.flow([(1340, 640 - 50), (1308, 590), (1308, 793), (1276, 793)], "main")
    d.vt(1302, 690, "kart: token PAN", 12, "#1f1f1f", 600)
    # auth -> kimlik
    d.flow([(448, 576), (448, 606), (1290, 606), (1290, 700), (1340, 700)], "aux")
    d.text(1186, 702, "auth-proxy → IdP", 11.5, 400, "#5f5f5a", "end")
    # internal -> core/data/çıkış
    d.flow([(300, 904), (300, 926)], "main")
    d.text(312, 920, "core-adapter → mTLS", 12, 600)
    d.flow([(900, 904), (900, 926)], "main")
    d.text(912, 920, ":5432 · :9093 · :6379 · :5671 (mTLS)", 12, 600)
    d.flow([(1276, 880), (1340, 880)], "main")
    d.text(1288, 872, "int-egressgw", 11.5, 600, anchor="start")
    # dış çıkış -> dış dünya, pci -> şemalar
    d.flow([(1820, 830), (1886, 830)], "req", "proxy", 1826, 822)
    d.flow([(1820, 760), (1840, 760), (1840, 722), (1886, 722)], "req", "VPN / hat", 1822, 714)
    d.flow([(1820, 480), (1886, 480)], "aux", "özel hat", 1824, 472)
    d.flow([(1276, 1052), (1340, 1052)], "aux", "CDC", 1290, 1046)
    d.text(1260, 1124, "tüm cluster'lar → mgmt: log · metrik · iz (tek yönlü)", 12.5, 600, "#1f5f1f", "end")

    # Okuma sırası ve lejant
    idx = ["00 · genel bakış (bu resim)", "01 · giriş: internet edge, şube ağı, ATM / POS", "02 · DMZ cluster: node havuzu, namespace, pod",
           "03 · DMZ pod içi: gateway, token handler, auth-proxy", "04 · internal cluster: domain namespace'leri, waypoint'ler",
           "05 · internal pod içi: ödeme servisi örneği", "06 · veri, core banking, PCI cluster'ları", "07 · kimlik ve yönetim / gözlem",
           "08 · bir node'un anatomisi: agent'lar, ztunnel, HBONE", "09 · uçtan uca istek: mobil transfer, adım adım"]
    d.note(40, 1290, 620, "Okuma sırası · siyah etiket = ayrıntı resmi", idx)
    d.legend(680, 1290, 1500, ZONES_ALL, extra=True, cols=5)
    d.save(out("00-genel-bakis.svg"), "00 · Genel bakış: kanal → zone → cluster → veri → dış dünya (hedef prod mimarisi)",
           "2 DC aktif-aktif · OpenShift · Istio ambient · her blok siyah etiketteki resimde açılır · yeşil = giriş, turuncu = çıkış · mavi = mTLS ana akış",
           oy=OY)


# =====================================================================================================================
def img01():
    W, H, OY = 2200, 1330, 40
    d = D(W, H)
    d.boundary([(20, 90), (1250, 90), (1250, 218), (20, 218)], "İNTERNET", "public", fill_opacity=0.5)
    d.boundary([(1270, 90), (2180, 90), (2180, 218), (1270, 218)], "KURUM WAN · ÖZEL AĞ (İNTERNETTEN AYRI)", "wan", fill_opacity=0.6)
    d.boundary([(14, 236), (2186, 236), (2186, 1090), (14, 1090)], "BANKA PERİMETRESİ", "external")
    d.boundary([(1890, 790), (2172, 790), (2172, 1000), (1890, 1000)], "PCI DSS", "pci", label_at=(1906, 776))

    # İstemciler
    for i, (t, s_) in enumerate([("Tarayıcı", "ib · stream (WSS)"), ("Mobil uygulama", "m-api · stream (WSS)"), ("Partner sunucusu", "api · mTLS + client secret")]):
        d.channel(40 + i * 405, 112, 385, t, s_, h=78)
    for i, (t, s_) in enumerate([("Şube terminali", "cihaz sertifikası"), ("ATM", "NDC / DDC"), ("POS", "ISO 8583")]):
        d.channel(1290 + i * 296, 112, 280, t, s_, h=78)

    # ---------------- İnternet yolu
    d.zone(40, 256, 1210, 820, "Internet Edge · DC1 ve DC2'de aynı yapı (aktif-aktif) · Kubernetes dışı cihazlar", color="edge", title_above=True)
    dev = [("1 · ISS + bulut scrubbing (DDoS)", ["L3/L4 hacim saldırısı süzülür", "BGP anycast · temiz trafik banka hattına"], "in any → :443 TCP", "out :443 temiz trafik"),
           ("2 · GSLB / DNS", ["ib / m-api / api / auth / stream → DC1 ya da DC2 VIP", "sağlık kontrolü · DNSSEC · coğrafi yönlendirme"], "in :53 DNS", "out yanıt: VIP adresi"),
           ("3 · Perimeter NGFW (DC başına HA çift)", ["yalnızca 443/TCP · IPS · geo-IP · itibar listesi", "SYN koruma · bağlantı limiti"], "in :443 TCP", "out :443 → F5 VIP"),
           ("4 · F5 LTM + Advanced WAF (HA çift)", ["TLS 1.3 sonlandırma (anahtar HSM'de) · HTTP/2 · WSS upgrade", "OWASP · bot koruma · header temizliği (X-Forwarded-*, x-user-jwt)",
                                                     "5xx gövdesi maskelenir · istek / bağlantı limiti · partner: mTLS"], "in :443 HTTPS / WSS", "out :443 mTLS (Edge-DMZ CA)")]
    y = 310
    for i, (t, ls, bi, bo) in enumerate(dev):
        h = 50 + 18 * len(ls)
        d.box(64, y, 700, h, t, ls, color="edge")
        d.badge(784, y + 24, bi, "in")
        d.badge(784, y + 48, bo, "out")
        if i < 3:
            d.flow([(414, y + h), (414, y + h + 22)], "req")
        y += h + 22
    # F5 VIP tablosu
    vx, vy = 64, y + 6
    d.text(vx, vy + 4, "F5 VIP'leri (DC başına) → DMZ hedefi", 14, 700)
    rows = [("ib.banka.com.tr :443", "web · CSP · CSRF", "dmz-ingressgw (edge-web)"),
            ("stream.banka.com.tr :443", "WSS · Origin allowlist", "realtime (edge-web / edge-mobile)"),
            ("m-api.banka.com.tr :443", "mobil · bot · sürüm", "mobile-gw (edge-mobile)"),
            ("api.banka.com.tr :443", "mTLS (Partner CA) · FAPI", "partner-gw (edge-partner)"),
            ("auth.banka.com.tr :443", "giriş sayfası · OIDC", "dmz-ingressgw → kimlik zone")]
    for i, (a, b, c) in enumerate(rows):
        ry = vy + 16 + i * 30
        d.n.append(f'<rect x="{vx}" y="{ry}" width="1160" height="26" rx="4" fill="{"#fffaf0" if i % 2 else "#ffffff"}" stroke="#e2b04a" stroke-width="0.8"/>')
        d.text(vx + 10, ry + 18, a, 12.5, 700)
        d.text(vx + 330, ry + 18, b, 12.5)
        d.text(vx + 680, ry + 18, "→ " + c, 12.5, 600)
    d.firewall(40, 1040, 1200, 22, "İÇ FIREWALL (farklı üretici) · yalnızca F5 iç IP'leri → DMZ VIP'leri :443 · başka her şey düşer", tx=180)
    d.badge(430, 1106, "out → DMZ: 02 · 03", "out")

    # ---------------- Şube yolu
    d.zone(1270, 256, 600, 480, "Şube zone · kurum WAN", color="wan", title_above=True)
    br = [("Şube terminali / gişe PC", ["kurumsal cihaz · TPM · NAC", "cihaz sertifikası (kurum PKI)"], "in kullanıcı: AD girişi", "out :443 mTLS (cihaz sert.)"),
          ("SD-WAN / MPLS hub", ["şube → DC hattı (şifreli)", "internet edge'inden geçmez"], "in şube hattı", "out :443 → branch-fw"),
          ("branch-fw (NGFW, HA)", ["yalnızca :443 → branch-gw", "şube IP aralığı izin listesi"], "in :443", "out :443 → branch-gw"),
          ("branch-gw A / B (şube gateway)", ["cihaz sert. ↔ şube kodu eşleşmesi", "Kerberos / AD → Keycloak personel girişi", "mesai saati · rol (gişe / yetkili)"], "in :443 mTLS", "out mTLS + iç JWT")]
    y = 310
    for i, (t, ls, bi, bo) in enumerate(br):
        h = 50 + 18 * len(ls)
        d.box(1294, y, 330, h, t, ls, color="wan")
        d.badge(1636, y + 22, bi, "in")
        d.badge(1636, y + 46, bo, "out")
        if i < 3:
            d.flow([(1459, y + h), (1459, y + h + 14)], "req")
        y += h + 14
    d.badge(1860, 728, "out → internal int-ingressgw (04)", "out", anchor="end")

    # ---------------- ATM / POS
    d.zone(1890, 256, 282, 480, "ATM · POS ağı", color="wan", title_above=True)
    d.box(1906, 310, 250, 96, "atm-fw", ["özel ATM ağı (kiralık hat)", "TID izin listesi"], color="wan")
    d.badge(1906, 428, "in NDC / DDC (TLS)", "in")
    d.box(1906, 446, 250, 110, "APN gw · pos-fw", ["GSM APN (özel) / sabit hat", "MID / TID izin listesi", "ISO 8583 (TLS)"], color="wan")
    d.badge(1906, 578, "in ISO 8583 (TLS)", "in")
    d.text(1906, 616, "terminal sertifikası · cihaz", 12, 400, "#3a3a3a")
    d.text(1906, 634, "anahtarı (RKL) · PCI kapsamı", 12, 400, "#3a3a3a")
    d.badge(2160, 712, "out → PCI cluster (06)", "out", anchor="end")
    d.zone(1906, 806, 252, 180, "ocp-pci (06)", ["atm-switch · pos-switch", "iso8583-adapter", "HSM: PIN · CVV"], color="pci")

    # Akışlar
    for i in range(2):
        x = 40 + i * 405 + 192
        d.flow([(x, 190), (x, 310)], "req")
    d.flow([(1002, 190), (1002, 290), (700, 290), (700, 310)], "req")
    d.flow([(1430, 190), (1430, 310)], "req")
    d.flow([(1726, 190), (1726, 256), (2031, 256), (2031, 310)], "req")
    d.flow([(2022, 190), (2022, 240), (2100, 240), (2100, 446)], "req")
    d.flow([(2031, 556), (2031, 806)], "main", "TLS", 2040, 650)
    d.flow([(1459, 700), (1459, 740), (1459, 1108)], "main")
    d.vt(1450, 920, "şube → internal: mTLS + iç JWT", 12.5, "#1f1f1f", 600)
    d.flow([(414, 1000), (414, 1108)], "main")
    # Yasak yollar
    d.flow([(1258, 200), (1258, 1040), (1880, 1040), (1880, 900), (1900, 900)], "deny", "internet → şube / ATM / POS / PCI: yol yok", 1500, 1032)

    d.note(40, 1130, 700, "Bu resimde", ["İnternet kanalları dört katmandan geçer: DDoS → GSLB → NGFW → F5 (WAF). Her katman kendi kontrolünü yapar.",
                                         "Şube ve ATM / POS internet edge'ini hiç kullanmaz: kurum WAN'ı ve kendi firewall'ları.",
                                         "Kart verisi (PAN) yalnızca PCI cluster'ında; internal'a token gider (06).",
                                         "DMZ'nin içi: 02 (cluster) ve 03 (pod); şube gw → internal: 04."], 12.5)
    d.legend(760, 1130, 1420, [("public", "internet"), ("wan", "kurum WAN"), ("edge", "edge"), ("pci", "PCI")], extra=True, cols=5)
    d.save(out("01-giris-edge-sube-atm.svg"), "01 · Giriş katmanı: internet edge, şube ağı, ATM / POS",
           "Kubernetes dışı cihazlar · her cihazda giriş (yeşil) ve çıkış (turuncu) portu · kırmızı kesikli: olmayan / yasak yol", oy=OY)


# =====================================================================================================================
def img02():
    W, H, OY = 2200, 1300, 40
    d = D(W, H)
    d.boundary([(20, 96), (2180, 96), (2180, 1010), (20, 1010)], "DMZ · ocp-dmz (DC1; DC2'de aynısı) · iş mantığı ve veri yok", "dmz", fill_opacity=0.18)
    # Giriş / çıkış sütunu
    d.badge(40, 128, "in ← F5 :443 (Edge-DMZ CA mTLS): ib · stream · auth · m-api · api", "in")
    d.badge(2160, 128, "out → internal int-ingressgw :443 (04) · kimlik zone :443 (07) · mgmt: log / metrik / iz (07)", "out", anchor="end")

    # ---- Infra node havuzu: gateway'ler
    d.zone(40, 156, 1060, 640, "Infra node havuzu (taint: infra) · gateway'ler · ayrı node'lar", color="dmz", title_above=True)
    gw = [("istio-ingress", "dmz-ingressgw", "Deployment ×3", [("istio-proxy", "proxy", ["Envoy · :443 ib / stream / auth VIP'leri", "TLS · WSS upgrade · header temizliği"])]),
          ("edge-mobile", "mobile-gw", "Deployment ×3", [("istio-proxy", "proxy", ["Envoy · :443 m-api · kota 30 rps", "ext_authz → auth-proxy (DPoP, attestation)"])]),
          ("edge-partner", "partner-gw", "Deployment ×2", [("istio-proxy", "proxy", ["Envoy · :443 api · mTLS (Partner CA)", "partner başına kota · ext_authz"])]),
          ("istio-egress", "dmz-egressgw", "Deployment ×3", [("istio-proxy", "proxy", ["Envoy · internal'a TEK kapı", "port + kimlik AuthZ · mTLS (ISTIO_MUTUAL)"])])]
    for i, (ns, pod, kind, cs) in enumerate(gw):
        x = 60 + (i % 2) * 525
        y = 210 + (i // 2) * 290
        d.nsbox(x, y, 505, 270, ns, "dmz")
        d.pod(x + 14, y + 42, 477, 112, pod, kind, "dmz", cs)
        d.text(x + 18, y + 176, "Service: LoadBalancer VIP (F5 arkasında)" if ns != "istio-egress" else "Service: ClusterIP (yalnızca DMZ içinden)", 12)
        d.text(x + 18, y + 196, "SPIFFE: corp.mesh/ns/" + ns + "/sa/" + pod, 12, 400, "#5f5f5a")
        d.text(x + 18, y + 216, "HPA · PodDisruptionBudget · node anti-affinity (DC içinde 2 node)", 12, 400, "#5f5f5a")
    d.badge(330, 228, "in :443", "in")
    d.badge(855, 228, "in :443", "in")
    d.badge(330, 518, "in :443 mTLS", "in")
    d.badge(1050, 744, "out → int-ingressgw :443", "out", anchor="end")
    # ---- Worker havuzu
    d.zone(1120, 156, 1060, 640, "Worker node havuzu · uygulama pod'ları · her namespace'te waypoint (L7)", color="dmz", title_above=True)
    d.nsbox(1140, 210, 505, 330, "edge-web", "dmz", "ambient · waypoint")
    cy = d.pod(1154, 252, 230, 118, "web-static", "Deployment ×2", "dmz", [("nginx", "app", ["SPA dosyaları", "CSP · HSTS"])])
    d.pod(1394, 252, 237, 118, "web-token-handler", "Deploy ×3", "dmz", [("handler (Go)", "app", [":8080 · cookie ↔ token", "CSRF · WSS bileti"])])
    d.pod(1154, 382, 477, 72, "waypoint", "Deployment ×2", "dmz", [("istio-proxy", "proxy", ["L7: yalnızca dmz-ingressgw → token handler"])])
    d.text(1154, 482, "token handler → auth-proxy (iç JWT) → dmz-egressgw → web-bff", 12)
    d.text(1154, 502, "oturum: dmz-redis (yalnızca oturum öneki, ACL)", 12, 400, "#5f5f5a")
    d.nsbox(1665, 210, 495, 330, "auth", "dmz", "ambient · waypoint")
    d.pod(1679, 252, 467, 126, "auth-proxy", "Deployment ×3 · HPA", "dmz",
          [("auth-proxy (Go)", "app", [":8080 ext_authz · introspection + RFC 8693 exchange", "DPoP · attestation · kanal kuralları · 30 sn önbellek"])])
    d.pod(1679, 390, 467, 72, "waypoint", "Deployment ×2", "dmz", [("istio-proxy", "proxy", ["L7: yalnızca gateway'ler ve token handler çağırır"])])
    d.text(1679, 488, "→ IdP (kimlik zone) :443 · → dmz-redis (DPoP jti, SET NX)", 12)
    d.text(1679, 508, "secret: exchange client'ları (Vault → ESO)", 12, 400, "#5f5f5a")
    d.nsbox(1140, 556, 505, 228, "ratelimit", "dmz")
    d.pod(1154, 598, 230, 100, "ratelimit", "Deployment ×2", "dmz", [("ratelimit", "app", [":8081 gRPC · global kota"])])
    d.pod(1394, 598, 237, 118, "dmz-redis", "StatefulSet ×3", "dmz", [("redis + sentinel", "data", ["sayaç · DPoP jti · oturum", "ACL: önek başına kullanıcı"])])
    d.text(1154, 744, "kota erişilemezse fail-open; local kota korur", 12, 400, "#5f5f5a")
    d.nsbox(1665, 556, 495, 228, "istio-system · logging-agent · monitoring", "mgmt")
    d.pod(1679, 598, 225, 72, "istiod", "Deployment ×2", "mgmt", [("discovery", "app", [":15012 xDS · CA"])])
    d.pod(1914, 598, 232, 72, "prometheus-agent", "Deploy ×1", "mgmt", [("prometheus", "agent", ["→ mgmt remote_write"])])
    d.pod(1679, 680, 150, 90, "ztunnel", "DaemonSet", "mgmt", [("ztunnel", "agent", [":15008 HBONE"])], agent=True)
    d.pod(1837, 680, 150, 90, "istio-cni", "DaemonSet", "mgmt", [("install-cni", "agent", ["nftables"])], agent=True)
    d.pod(1995, 680, 151, 90, "fluent-bit", "DaemonSet", "mgmt", [("fluent-bit", "agent", ["→ mgmt loglar"])], agent=True)

    # Akışlar
    d.flow([(330, 140), (330, 252)], "main")
    d.flow([(855, 140), (855, 252)], "main")
    d.flow([(1046, 380), (1046, 820), (1912, 820), (1912, 378)], "aux")
    d.text(1400, 838, "ext_authz: her kanal, her istek → auth-proxy (iç JWT gateway'e döner)", 12.5, 600, "#1f1f1f")
    d.flow([(585, 672), (585, 1040)], "main", "mTLS :443 + iç JWT → int-ingressgw (04)", 597, 1034)
    # Yasak
    d.flow([(1500, 880), (1500, 1040)], "deny", "DMZ → veri zone (PostgreSQL, Kafka, core): yol yok", 1512, 1034)

    d.note(40, 856, 1100, "Bu resimde", ["Gateway'ler ayrı node'larda (infra): internetten gelen trafiği karşılayan pod'lar uygulama pod'larıyla aynı node'u paylaşmaz.",
                                          "Uygulama namespace'leri ambient: pod'larda sidecar yok; mTLS node'daki ztunnel'de, L7 kurallar namespace'in waypoint'inde.",
                                          "Kanallar (ib → token handler, m-api, api) isteği iç JWT ile dmz-egressgw'ye verir: internal'a tek kapı. Dış token DMZ'de kalır.",
                                          "DMZ'den veri ve core zone'una yol yok.",
                                          "Pod'un içi (container, port, filtre zinciri, agent'lar): 03."], 12.5)
    d.legend(40, 1056, 2140, [("dmz", "DMZ"), ("mgmt", "platform / gözlem")], extra=True, cols=6)
    d.save(out("02-dmz-cluster.svg"), "02 · DMZ cluster'ı (ocp-dmz): node havuzları, namespace'ler, pod'lar",
           "her pod: ad · iş yükü türü · replika · container'lar · ne yaptığı · yeşil = giriş, turuncu = çıkış", oy=OY)


# =====================================================================================================================
def img03():
    W, H, OY = 2200, 1290, 40
    d = D(W, H)
    d.boundary([(14, 96), (2186, 96), (2186, 900), (14, 900)], "DMZ · ocp-dmz · iki node'un içi", "dmz", fill_opacity=0.15)
    # ---- Infra node: mobile-gw
    d.node(40, 130, 1050, 750, "infra-node-1 (RHCOS · CRI-O · kubelet)", "taint: infra · yalnızca gateway pod'ları")
    d.nsbox(60, 172, 1010, 316, "edge-mobile", "dmz")
    gb = d.pod(80, 210, 970, None, "mobile-gw-7c9f…", "Deployment ×3 · SA mobile-gw", "dmz", [
        ("istio-proxy (Envoy) · gateway modu: Envoy pod'un kendisi (sidecar değil)", "proxy", [
            "listener :443 · TLS (m-api sertifikası) · istemci sertifikası yalnızca Edge-DMZ CA (F5)",
            "filtre 1 · header temizliği: dışarıdan gelen x-channel / x-user-jwt / x-forwarded-* silinir; x-channel=mobile",
            "filtre 2 · local rate limit (30 rps) · CORS · istek boyutu sınırı",
            "filtre 3 · ext_authz → auth-proxy.auth:8080 (DPoP, attestation, introspection, exchange); ret: 401 / 403 / 426",
            "filtre 4 · global kota → ratelimit.ratelimit:8081 (gRPC)",
            "route · /mobile/v1/* → önek kaldırılır → dmz-egressgw:443 (Host: mobile-bff.internal) · iç JWT eklenir",
            "erişim logu (JSON: request_id, channel, trace_id) → stdout · iz → OTLP (%10)",
            "yönetim: :15021 sağlık · :15090 metrik (Prometheus) · :15000 admin (yalnızca pod içi)"]),
        ("pilot-agent", "agent", ["xDS → istiod :15012 (mTLS) · sertifika yenileme (SPIFFE, 24 saat)"])])
    d.badge(80, gb + 26, "in :443 ← F5 (yalnızca Edge-DMZ CA)", "in")
    d.badge(1050, gb + 26, "out → auth-proxy :8080 · ratelimit :8081 · dmz-egressgw :443", "out", anchor="end")
    ay = gb + 64
    d.text(60, ay, "Node agent'ları (her node'da bir tane · DaemonSet)", 14, 700)
    ag = [("ztunnel", ["istio-system · L4 mTLS", "in :15008 HBONE", "çıkış yakalama :15001", "DNS proxy :15053"]),
          ("istio-cni", ["pod ağına nftables kuralı", "yazar: pod trafiği", "ztunnel'e yönlenir", "(pod'a yetki gerekmez)"]),
          ("fluent-bit", ["/var/log/pods (salt okunur)", "zenginleştirme · maskeleme", "kategori → Loki tenant'ı", "→ mgmt (yalnızca push)"]),
          ("node-exporter", ["node metrikleri :9100", "→ prometheus-agent", "→ mgmt (remote_write)", ""])]
    for k, (n, ls) in enumerate(ag):
        d.pod(60 + k * 254, ay + 14, 244, None, n, "DaemonSet", "mgmt", [(n, "agent", [l for l in ls if l])], agent=True)
    d.note(60, ay + 170, 1010, "Gateway pod'u neden farklı?", [
        "Gateway Envoy'un kendisidir: trafiği karşılayan, TLS'i sonlandıran ve kuralları uygulayan container bu.",
        "Uygulama pod'larında Envoy yok (ambient): mTLS'i node'daki ztunnel, L7 kurallarını namespace'in waypoint'i yapar.",
        "Gateway → auth-proxy çağrısı da mesh içinden gider: HBONE (mTLS) ile auth namespace'inin waypoint'ine."], 12.5)

    # ---- Worker node
    d.node(1110, 130, 1050, 750, "worker-node-3 (RHCOS · CRI-O · kubelet)", "uygulama pod'ları · sidecar yok")
    d.nsbox(1130, 172, 1010, 318, "auth", "dmz", "istio.io/use-waypoint: waypoint")
    wb = d.pod(1150, 210, 470, None, "waypoint-5d8…", "Deployment ×2", "dmz", [
        ("istio-proxy (Envoy) · L7", "proxy", ["in :15008 HBONE (yalnızca mesh kimlikleri)", "AuthZ: kaynak = gateway'ler, token handler",
                                                 "zaman aşımı · yeniden deneme · erişim logu", "iz span'i (OTLP)"])])
    d.pod(1640, 210, 480, None, "auth-proxy-6b…", "Deployment ×3 · SA auth-proxy", "dmz", [
        ("auth-proxy (Go, distroless, non-root)", "app", [":8080 HTTP ext_authz kontrol ucu", "salt okunur kök dosya sistemi · yetenek yok",
                                                         "token önbelleği (30 sn) · tekil istek birleştirme"]),
        ("secret (Vault → External Secrets)", "data", ["exchange client secret'ları", "attestation açık anahtarı (salt okunur)"]),
        ("kimlik", "init", ["SPIFFE: corp.mesh/ns/auth/sa/auth-proxy", "sertifikayı ztunnel tutar (pod'da anahtar yok)"])])
    for k, (t, kind) in enumerate([("in ← gateway'ler (HBONE :15008)", "in"), ("out → IdP :443 (dmz-egressgw üzerinden)", "out"),
                                   ("out → dmz-redis :6379 (jti, SET NX)", "out"), ("out → device-registry (kimlik zone)", "out")]):
        d.badge(1150, wb + 24 + k * 26, t, kind)
    d.nsbox(1130, 506, 1010, 150, "edge-web", "dmz", "ambient · waypoint")
    d.pod(1150, 544, 470, None, "web-token-handler-…", "Deployment ×3", "dmz", [
        ("handler (Go)", "app", [":8080 · __Host-sid ↔ token (Valkey)", "CSRF · refresh rotation · WSS bileti"])])
    d.pod(1640, 544, 480, None, "waypoint-…", "Deployment ×2", "dmz", [
        ("istio-proxy (Envoy) · L7", "proxy", ["yalnızca dmz-ingressgw → token handler", "yöntem ve yol kuralları"])])
    d.pod(1130, 672, 1010, 34, "ztunnel · istio-cni · fluent-bit · node-exporter (soldaki node ile aynı DaemonSet'ler)", "DaemonSet", "mgmt", [], agent=True)
    d.note(1130, 724, 1010, "İstek yolu (numaralar)", [
        "1  F5 → mobile-gw :443 (TLS, Edge-DMZ CA)    2  mobile-gw → HBONE :15008 mTLS → auth waypoint",
        "3  waypoint: kaynak kimliği gateway mi?    4  waypoint → auth-proxy :8080 (ztunnel üzerinden)",
        "5  auth-proxy → dmz-redis (jti) · IdP (introspection + exchange) → iç JWT",
        "6  karar + iç JWT mobile-gw'ye döner    7  mobile-gw → dmz-egressgw :443 → internal (04)"], 12.5)
    # Akışlar ve numaralar
    d.flow([(560, 98), (560, 210)], "main")
    d.marker(576, 150, 1, "#1d7a46")
    d.flow([(1050, 300), (1100, 300), (1100, 260), (1150, 260)], "main")
    d.marker(1100, 282, 2, "#2f7bd8")
    d.marker(1385, 202, 3, "#2f7bd8")
    d.flow([(1620, 280), (1640, 280)], "main")
    d.marker(1630, 262, 4, "#2f7bd8")
    d.marker(1610, wb + 76, 5, "#c2410c")
    d.flow([(1150, 330), (1080, 330), (1080, 360), (1050, 360)], "req")
    d.marker(1080, 380, 6, "#1f1f1f")
    d.flow([(80, 440), (30, 440), (30, 930)], "main", "→ dmz-egressgw :443 → internal (04)", 42, 924)
    d.marker(30, 600, 7, "#2f7bd8")
    d.legend(40, 950, 2140, [("dmz", "DMZ"), ("mgmt", "platform / gözlem")], extra=True, cols=6)
    d.save(out("03-dmz-pod-detay.svg"), "03 · DMZ pod içi: gateway (Envoy), auth-proxy, token handler, waypoint ve node agent'ları",
           "pod → container → port ve görev · numaralar: mobil isteğin DMZ içindeki yolu · ambient: uygulama pod'larında sidecar yok", oy=OY)


# =====================================================================================================================
def ns_pods(d, x, y, w, ns, pods, color="internal", sub=None):
    """Namespace + pod listesi (her pod tek satır: ad · tür); döndürür: alt kenar"""
    h = 40 + len(pods) * 40
    d.nsbox(x, y, w, h, ns, color, sub)
    for i, (name, kind, desc) in enumerate(pods):
        agent = kind.startswith("DaemonSet")
        col = "mgmt" if agent else ("dmz" if name.startswith("waypoint") or "gw" in name else color)
        d.pod(x + 12, y + 36 + i * 40, w - 24, 34, name, kind, col, (), agent=agent)
        if desc:
            d.text(x + 12 + (w - 24) * 0.42, y + 36 + i * 40 + 19, desc, 11.5, 400, "#3a3a3a")
    return y + h


def img04():
    W, H, OY = 2200, 1640, 40
    d = D(W, H)
    d.boundary([(14, 96), (2186, 96), (2186, 1250), (14, 1250)], "INTERNAL · ocp-apps A (DC1; B / DC2 aynısı) · private zone", "internal", fill_opacity=0.12)
    d.badge(40, 128, "in ← dmz-egressgw · branch-gw · kart zone :443 (mTLS + iç JWT)", "in")
    d.badge(2160, 128, "out → core :443 · data :5432 :9093 :6379 :5671 · dış çıkış (proxy) · mgmt (log / metrik / iz)", "out", anchor="end")
    c = [40, 760, 1480]
    cw = 680
    # Satır 1
    b1 = ns_pods(d, c[0], 160, cw, "istio-ingress (infra node)", [("int-ingressgw", "Deployment ×3", "MUTUAL TLS :443 · yalnızca gateway kimlikleri"),
                                                                    ("RequestAuthentication", "", "iç JWT: Keycloak JWKS · ≤ 2 dk")])
    b2 = ns_pods(d, c[1], 160, 2 * cw + 40, "channel-bff", [("web-bff", "Deployment ×3", "web kanalının arka ucu · ekran için birleştirme"),
                                                         ("mobile-bff", "Deployment ×3", "mobil · cihaz uçları · step-up ipucu"),
                                                         ("branch-bff", "Deployment ×2", "şube · mesai saati · dört göz"),
                                                         ("realtime-gw", "Deployment ×3", "WSS bağlantıları · abonelik ACL · Kafka'dan olay"),
                                                         ("waypoint", "Deployment ×2", "L7: kanal ↔ BFF eşlemesi (channel claim)")], sub="ambient · waypoint")
    # Domain namespace'leri
    doms = [("hesap", [("account-api", "Deployment ×3", "hesap · bakiye · BOLA (sahiplik)"), ("statement", "Deployment ×2", "hesap hareketleri"),
                       ("waypoint", "Deployment ×2", "scope accounts:read · kanal")]),
            ("odeme", [("transfer", "Deployment ×3", "transfer · idempotency · saga (05)"), ("eft-fast", "Deployment ×2", "EFT / FAST mesajları"),
                       ("orchestrator", "Deployment ×2", "saga koordinasyonu"), ("waypoint", "Deployment ×2", "transfers:write · acr ≥ 2")]),
            ("kart", [("card-api", "Deployment ×2", "yalnızca token PAN"), ("limit", "Deployment ×2", "limit · kampanya"),
                      ("waypoint", "Deployment ×2", "→ kart zone (tokenization)")]),
            ("kredi", [("loan-app", "Deployment ×2", "başvuru"), ("scoring", "Deployment ×2", "skorlama · KKB (egress)"),
                       ("waypoint", "Deployment ×2", "rol + scope")]),
            ("musteri", [("customer", "Deployment ×2", "müşteri kaydı"), ("kyc", "Deployment ×2", "kimlik doğrulama · NFC"),
                         ("onboarding", "Deployment ×2", "e-imza"), ("waypoint", "Deployment ×2", "personel / müşteri ayrımı")]),
            ("security · AI", [("fraud-svc", "Deployment ×3", "Kafka Streams · risk skoru"), ("ai-gateway", "Deployment ×2", "PII maskeleme · kota · log"),
                               ("model-serving", "Deployment ×1", "GPU node · on-prem model"), ("rag-svc", "Deployment ×2", "onaylı kaynaklar"),
                               ("waypoint", "Deployment ×2", "yalnızca iç çağrılar")]),
            ("bildirim", [("notifier", "Deployment ×2", "SMS · push · e-posta (Kafka tüketici)"), ("waypoint", "Deployment ×2", "→ dış çıkış")]),
            ("integration", [("core-adapter", "Deployment ×3", "anti-corruption · core'a tek yol"), ("waypoint", "Deployment ×2", "yalnızca domain servisleri")]),
            ("raporlama", [("report-api", "Deployment ×2", "ekstre · dekont"), ("statement-batch", "CronJob", "gece üretimi"),
                           ("waypoint", "Deployment ×2", "")])]
    y0 = max(b1, b2) + 20
    rows_y = [y0, 0, 0]
    bottoms = [0, 0, 0]
    for i, (ns, pods) in enumerate(doms):
        col = i % 3
        row = i // 3
        y = y0 if row == 0 else bottoms[col] + 16
        bottoms[col] = ns_pods(d, c[col], y, cw, ns, pods, sub="ambient · waypoint")
    y = max(bottoms) + 16
    e1 = ns_pods(d, c[0], y, cw, "istio-egress (infra node)", [("int-egressgw", "Deployment ×3", "TEK çıkış · port + kimlik AuthZ · mTLS"),
                                                                ("ServiceEntry / DR", "", "core · data · proxy · REGISTRY_ONLY")])
    e2 = ns_pods(d, c[1], y, cw, "olay", [("debezium-connect", "Deployment ×2", "outbox → Kafka (CDC)"), ("schema-registry", "Deployment ×2", "Avro şemaları"),
                                          ("waypoint", "Deployment ×2", "")], sub="ambient · waypoint")
    e3 = ns_pods(d, c[2], y, cw, "istio-system · platform", [("istiod", "Deployment ×2", "xDS · sertifika (CA: Vault, istio-csr)"),
                                                            ("ztunnel · istio-cni", "DaemonSet", "her node: L4 mTLS · HBONE"),
                                                            ("fluent-bit · node-exporter", "DaemonSet", "log · metrik → mgmt"),
                                                            ("external-secrets · kyverno", "Deployment", "Vault → Secret · imzalı image")], color="mgmt")
    # Akışlar
    d.flow([(380, 112), (380, 196)], "main")
    d.flow([(720, 216), (772, 216)], "main", "→ BFF", 724, 206)
    d.text(c[1] + 12, b2 + 14, "BFF → domain servisleri: hedef namespace'in waypoint'i üzerinden (HBONE mTLS, iç JWT taşınır)", 12.5, 600, "#1f1f1f")
    bottom = max(e1, e2, e3)
    d.flow([(380, e1), (380, 1280)], "main", "int-egressgw → core :443 · data (mTLS) · dış çıkış (proxy)", 392, 1274)
    d.flow([(1100, 1200), (1100, 1280)], "deny", "pod → dış dünya (doğrudan): yol yok (REGISTRY_ONLY + NetworkPolicy)", 1112, 1274)
    d.note(40, 1300, 1080, "Bu resimde", ["Her domain kendi namespace'inde; her namespace'in kendi waypoint'i (L7 yetki: scope, acr, rol, kanal) var.",
                                          "Pod'lar arası her bağlantı mTLS (ztunnel, HBONE); kimlik pod'un servis hesabı (SPIFFE).",
                                          "Dışarı yalnızca int-egressgw'den; veri, core ve dış çıkış hedefleri ServiceEntry ile tanımlı.",
                                          "Pod'un içi (container, secret, kimlik, port): 05 · node anatomisi: 08."], 12.5)
    d.legend(1140, 1300, 1040, [("internal", "internal"), ("dmz", "gateway / waypoint"), ("mgmt", "platform")], extra=True, cols=3)
    d.save(out("04-internal-cluster.svg"), "04 · Internal cluster'ı (ocp-apps): domain namespace'leri, waypoint'ler, pod'lar",
           "her kutu bir namespace · içindeki satırlar pod'lar (ad · iş yükü · replika · görev) · gateway ve waypoint'ler turuncu kenarlı", oy=OY)


# =====================================================================================================================
def img05():
    W, H, OY = 2200, 1290, 40
    d = D(W, H)
    d.boundary([(14, 96), (2186, 96), (2186, 880), (14, 880)], "INTERNAL · ocp-apps · ödeme namespace'i, bir node", "internal", fill_opacity=0.12)
    d.node(40, 130, 1460, 730, "worker-node-7 (RHCOS · CRI-O · kubelet) · zone: DC1-a", "topologySpread: pod'lar node ve DC'lere dağıtılır")
    d.nsbox(60, 172, 1420, 490, "odeme", "internal", "istio.io/use-waypoint: waypoint · PSA restricted · NetworkPolicy: deny-default")
    wb = d.pod(80, 210, 560, None, "waypoint-7f4…", "Deployment ×2 · L7", "dmz", [
        ("istio-proxy (Envoy)", "proxy", ["in :15008 HBONE · yalnızca mesh kimlikleri",
                                          "RequestAuthentication: iç JWT (iss = Keycloak realm, aud internal-apis)",
                                          "AuthZ: kaynak = channel-bff SA'ları · scope transfers:write · acr ≥ 2",
                                          "VirtualService: zaman aşımı · yalnızca GET'te yeniden deneme",
                                          "DestinationRule: bağlantı havuzu · outlier detection",
                                          "erişim logu · iz span'i · metrik (:15090)"])])
    tb = d.pod(660, 210, 800, None, "transfer-5c7d…", "Deployment ×3 · HPA · PDB · SA transfer", "internal", [
        ("transfer (Java 21 / Go, distroless, non-root, salt okunur kök FS)", "app", [
            ":8080 HTTP · /actuator/health (liveness / readiness) · :9464 metrik",
            "Idempotency-Key kontrolü · saga adımı · outbox tablosuna olay (aynı transaction)",
            "iç JWT'den: sub (müşteri) · acr · scope · sid → yetki ve denetim kaydı"]),
        ("secret · config", "data", ["DB kullanıcısı: Vault database engine → kısa ömürlü (1 saat), External Secrets yeniler",
                                     "ConfigMap: limitler · zaman aşımları · feature flag"]),
        ("kimlik", "init", ["SPIFFE: corp.mesh/ns/odeme/sa/transfer · sertifika pod'da değil, ztunnel'de",
                            "projected SA token (aud: vault) · automountServiceAccountToken: false"])])
    d.badge(660, tb + 24, "in ← waypoint (HBONE :15008 → :8080)", "in")
    outs = ["out → hesap waypoint → account-api :8080 (bakiye, sahiplik)", "out → security waypoint → fraud-svc :8080 (risk skoru)",
            "out → integration → core-adapter :8080 → core (posting)", "out → postgres (int-egressgw :15432 → data :5432, mTLS)",
            "out → OTLP iz · stdout log (fluent-bit) · metrik (agent)"]
    for k, t in enumerate(outs):
        d.badge(660, tb + 50 + k * 26, t, "out")
    d.badge(80, wb + 24, "in ← int-ingressgw · channel-bff (HBONE)", "in")
    d.pod(60, 676, 1420, 34, "ztunnel (DaemonSet): bu node'daki tüm pod'ların mTLS'i ve L4 yetkisi · istio-cni · fluent-bit · node-exporter", "DaemonSet",
          "mgmt", [], agent=True)
    d.note(60, 724, 1420, "İstek yolu (numaralar)", [
        "1  mobile-bff → (ztunnel → HBONE mTLS) → ödeme waypoint: iç JWT, scope, acr, kaynak SA kontrolü    2  waypoint → transfer :8080",
        "3  transfer → hesap waypoint → account-api (sahiplik ve bakiye)    4  transfer → fraud-svc (risk; yüksek risk → step-up / insan onayı)",
        "5  transfer → PostgreSQL (int-egressgw üzerinden): transfer kaydı + outbox    6  debezium (olay ns) outbox'u Kafka'ya taşır → bildirim, raporlama"], 12.5)
    # Sağ panel: güvenlik bağlamı
    d.zone(1520, 130, 650, 730, "Pod'un güvenlik ve işletim ayarları", color="note")
    rows = [("İmaj", ["Harbor (iç registry) · cosign imzalı · SBOM", "Kyverno: imzasız / latest reddedilir"]),
            ("Çalışma", ["runAsNonRoot · readOnlyRootFilesystem", "seccomp RuntimeDefault · yetenek: hiçbiri", "PSA restricted (namespace)"]),
            ("Kaynak", ["requests / limits · HPA (CPU, istek sayısı)", "PDB: en az 2 çalışır · topologySpread (DC, node)"]),
            ("Kimlik", ["servis hesabı → SPIFFE kimliği (mesh)", "Kubernetes API token'ı yok (automount: false)"]),
            ("Secret", ["Vault → External Secrets → Secret (dosya)", "DB parolası kısa ömürlü, otomatik yenilenir"]),
            ("Ağ", ["NetworkPolicy: deny-default + izinli hedefler", "mesh: AuthorizationPolicy (L4 ztunnel, L7 waypoint)"]),
            ("Gözlem", ["stdout JSON log · iz (traceparent taşınır)", "metrik :9464 → prometheus-agent → mgmt"])]
    yy = 186
    for t, ls in rows:
        d.box(1540, yy, 610, 30 + 18 * len(ls), t, ls, color="internal")
        yy += 40 + 18 * len(ls)
    # Akışlar
    d.flow([(360, 98), (360, 210)], "main")
    d.marker(376, 112, 1, "#2f7bd8")
    d.flow([(640, 280), (660, 280)], "main")
    d.marker(650, 262, 2, "#2f7bd8")
    d.marker(644, tb + 46, 3, "#c2410c")
    d.marker(644, tb + 72, 4, "#c2410c")
    d.marker(644, tb + 124, 5, "#c2410c")
    d.flow([(1460, tb + 120), (1510, tb + 120), (1510, 910)], "main", "→ int-egressgw → data / core (04, 06)", 1498, 904, "end")
    d.legend(40, 930, 2140, [("internal", "internal"), ("dmz", "waypoint (Envoy)"), ("mgmt", "platform"), ("note", "ayarlar")], extra=True, cols=6)
    d.save(out("05-internal-pod-detay.svg"), "05 · Internal pod içi: ödeme (transfer) pod'u, waypoint'i ve çağırdığı servisler",
           "pod → container → port · kimlik ve secret · waypoint'in L7 kuralları · numaralar: transfer isteğinin yolu", oy=OY)


# =====================================================================================================================
def img06():
    W, H, OY = 2200, 1530, 40
    d = D(W, H)
    d.boundary([(14, 96), (1180, 96), (1180, 1130), (14, 1130)], "DATA ZONE · ocp-data + VM (private)", "data", fill_opacity=0.12)
    d.boundary([(1196, 96), (2186, 96), (2186, 480), (1196, 480)], "CORE BANKING · ocp-core / VM", "core", fill_opacity=0.12)
    d.boundary([(1196, 500), (2186, 500), (2186, 1130), (1196, 1130)], "PCI DSS · ocp-pci (ayrı cluster, ayrı segment)", "pci", fill_opacity=0.12)
    # ---- Data
    d.badge(40, 130, "in ← yalnızca int-egressgw kimlikleri: :5432 :9093 :6379 :5671 (mTLS)", "in")
    b = ns_pods(d, 40, 150, 1120, "data-ingress", [("data-ingressgw", "Deployment ×3", "TCP mTLS · port + kaynak kimliği · servis başına hedef")], color="data")
    d.nsbox(40, b + 16, 550, 300, "postgres (CloudNativePG)", "data")
    yy = b + 52
    for i, (n, role) in enumerate([("accounts-db-1", "primary"), ("accounts-db-2", "sync replika"), ("accounts-db-3", "replika")]):
        d.pod(54, yy, 522, None, n, "StatefulSet · " + role, "data", [("postgres + instance-manager", "data", [":5432 · TDE · servis başına rol"])])
        yy += 84
    d.nsbox(610, b + 16, 550, 300, "kafka (Strimzi, KRaft)", "data")
    yy = b + 52
    for i in range(3):
        d.pod(624, yy, 522, None, f"kafka-broker-{i}", "StatefulSet", "data", [("kafka", "data", [":9093 TLS · ACL (topic başına) · RF 3"])])
        yy += 84
    y2 = b + 332
    ns_pods(d, 40, y2, 550, "valkey", [("valkey-0..2", "StatefulSet ×3", "önbellek · oturum · ACL önek"), ("sentinel", "×3", "otomatik failover")], color="data")
    ns_pods(d, 610, y2, 550, "rabbitmq", [("rabbitmq-0..2", "StatefulSet ×3", "quorum queue · legacy entegrasyon"), ("schema / mm2", "Deployment", "MirrorMaker2 → DC2")], color="data")
    vy = y2 + 140
    d.text(40, vy, "VM / appliance (cluster dışı)", 14, 700)
    for i, (t, ls) in enumerate([("Oracle RAC", ["core DB · 2 node", "Data Guard → DC2 (sync)"]), ("MSSQL Always On", ["CRM · raporlama", "AG listener · TDE"]),
                                 ("Nesne depolama (S3)", ["ODF / MinIO · doküman", "yaşam döngüsü · WORM"]), ("Yedek", ["pgBackRest · Velero · RMAN", "immutable · şifreli"])]):
        d.box(40 + i * 282, vy + 12, 268, 82, t, ls, color="data")
    # ---- Core
    d.badge(1216, 130, "in ← yalnızca integration/core-adapter kimliği :443 (mTLS)", "in")
    ns_pods(d, 1216, 150, 950, "core-ingress", [("core-ingressgw", "Deployment ×2", "MUTUAL TLS · L7 yetki · tek giriş")], color="core")
    ns_pods(d, 1216, 250, 950, "core", [("core-app", "Deployment / VM", "ledger · posting · mevduat · kredi (Java EE / COBOL)"),
                                        ("eod-batch", "CronJob", "gün sonu 23:00 - 02:00 · faiz · mutabakat"),
                                        ("mq-bridge", "Deployment ×2", "IBM MQ ↔ RabbitMQ / Kafka (CDC)")], color="core")
    d.badge(2166, 460, "out → Oracle RAC (data) · CDC → Kafka", "out", anchor="end")
    # ---- PCI
    d.badge(1216, 534, "in ← internal kart ns (token PAN) :443 · ATM / POS ağı (ISO 8583 / NDC, TLS)", "in")
    ns_pods(d, 1216, 554, 950, "pci-ingress", [("pci-ingressgw", "Deployment ×2", "kaynak: card-api SA · atm-fw / pos-fw IP + sertifika")], color="pci")
    ns_pods(d, 1216, 654, 465, "atm", [("atm-switch", "Deployment ×2", "NDC / DDC"), ("atm-monitor", "Deployment ×1", "nakit · durum")], color="pci")
    ns_pods(d, 1701, 654, 465, "pos", [("pos-switch", "Deployment ×2", "ISO 8583"), ("3ds-acs", "Deployment ×2", "3-D Secure")], color="pci")
    ns_pods(d, 1216, 794, 950, "card", [("tokenization", "Deployment ×2", "PAN ↔ token (Vault Transit / HSM)"), ("iso8583-adapter", "Deployment ×2", "REST ↔ ISO 8583"),
                                        ("card-db", "StatefulSet ×3", "kart verisi (şifreli) · yalnızca bu ns")], color="pci")
    d.box(1216, 978, 465, 92, "HSM (payShield, appliance)", ["PIN · CVV · anahtar yönetimi (RKL)", "cluster dışı · ayrı ağ"], color="pci")
    d.box(1701, 978, 465, 92, "Kart şeması hatları", ["Visa · Mastercard · TROY · BKM", "özel hat (kiralık devre)"], color="external")
    # akışlar
    d.flow([(600, 112), (600, 150)], "main")
    d.flow([(1680, 112), (1680, 150)], "main")
    d.flow([(1680, 516), (1680, 554)], "main")
    d.flow([(1448, 1150), (1448, 1070)], "req")
    d.flow([(1180, 400), (1196, 400)], "aux")
    d.note(40, 1160, 1120, "Bu resimde", ["Veri servislerine yalnızca internal'ın int-egressgw'si ve servis başına kimlikle erişilir; DMZ'nin yolu yok.",
                                          "Her StatefulSet'in replikası DC içinde farklı node'larda; DC2'ye replikasyon (Data Guard, MirrorMaker2, CNPG replika cluster).",
                                          "PCI ayrı cluster ve segment: internal'a yalnızca token PAN gider; PAN, HSM ve kart DB'si PCI içinde kalır.",
                                          "Core'a tek yol core-adapter (integration ns); core'un çıkışı yalnızca Oracle ve CDC."], 12.5)
    d.legend(1180, 1160, 1000, [("data", "veri"), ("core", "core"), ("pci", "PCI"), ("external", "dış")], extra=True, cols=3)
    d.save(out("06-veri-core-pci.svg"), "06 · Veri, core banking ve PCI cluster'ları",
           "StatefulSet'ler (replika rolleri), giriş gateway'leri, VM / appliance'lar · yeşil = kim girebilir, turuncu = nereye çıkar", oy=OY)


# =====================================================================================================================
def img07():
    W, H, OY = 2200, 1420, 40
    d = D(W, H)
    d.boundary([(14, 96), (840, 96), (840, 1010), (14, 1010)], "KİMLİK ZONE · ocp-iam A / B (private)", "identity", fill_opacity=0.14)
    d.boundary([(856, 96), (2186, 96), (2186, 1010), (856, 1010)], "YÖNETİM VE GÖZLEM · ocp-mgmt (private, yalnızca yazma girişleri)", "mgmt", fill_opacity=0.14)
    # ---- Kimlik
    d.badge(30, 130, "in ← dmz-egressgw (auth-proxy, token handler) :443 · F5 auth VIP (giriş sayfası)", "in")
    b = ns_pods(d, 30, 150, 795, "iam-ingress", [("iam-ingressgw", "Deployment ×2", "yalnızca uygulama realm uçları · /admin kapalı")], color="identity")
    d.nsbox(30, b + 16, 795, 330, "keycloak", "identity", "ambient · waypoint")
    yy = b + 52
    for i in range(3):
        d.pod(44, yy, 767, None, f"keycloak-{i}", "StatefulSet ×3", "identity",
              [("keycloak (RHBK) + Infinispan", "app", ["realm: müşteri · partner · personel · MFA · step-up", "introspection · token exchange (RFC 8693) · JWKS"])])
        yy += 100
    y2 = b + 362
    b2 = ns_pods(d, 30, y2, 795, "iam-data · iam-svc", [("keycloak-db-1..3", "StatefulSet ×3", "PostgreSQL (CNPG) · sync replika"),
                                                       ("device-registry", "Deployment ×2", "mobil cihaz anahtarları"),
                                                       ("consent-svc", "Deployment ×2", "açık bankacılık rızası"),
                                                       ("waypoint", "Deployment ×2", "yalnızca auth-proxy · BFF'ler")], color="identity")
    d.box(30, b2 + 14, 385, 74, "HSM", ["realm imza anahtarları", "anahtar rotasyonu"], color="identity")
    d.box(440, b2 + 14, 385, 74, "AD / LDAP federasyonu", ["personel: Kerberos", "out :636 LDAPS"], color="external")
    # ---- Mgmt
    d.badge(872, 130, "in ← tüm cluster'ların egress gateway'leri: log · metrik · iz (yalnızca yazma uçları)", "in")
    m = ns_pods(d, 872, 150, 1300, "mgmt-ingress", [("mgmt-ingressgw", "Deployment ×3", "logs / metrics / traces · POST yalnızca · sorgu dışarıya kapalı")], color="mgmt")
    cols = [872, 1311, 1750]
    cw = 422
    blocks = [("logging", [("log-kafka", "StatefulSet ×3", "log topic · tampon"), ("logstash", "Deployment ×3", "ayrıştırma · maskeleme"),
                           ("elasticsearch", "StatefulSet ×5", "sıcak / ılık"), ("kibana", "Deployment ×2", "rol bazlı")]),
              ("monitoring", [("thanos-receive", "StatefulSet ×3", "remote_write"), ("thanos-query · store", "Deployment", "uzun saklama"),
                              ("alertmanager", "StatefulSet ×3", "nöbet"), ("grafana", "Deployment ×2", "SLO panoları")]),
              ("tracing", [("otel-collector", "Deployment ×2", "örnekleme · zenginleştirme"), ("tempo", "StatefulSet ×3", "izler"),
                           ("kiali", "Deployment ×1", "mesh görünümü")]),
              ("siem-forwarder", [("siem-forwarder", "Deployment ×2", "→ QRadar / Splunk"), ("worm-archive", "CronJob", "Object Lock")]),
              ("vault", [("vault-0..2", "StatefulSet ×3", "Raft · auto-unseal (HSM)"), ("PKI · DB · Transit", "", "istio-csr · dinamik kimlik")]),
              ("platform", [("harbor", "Deployment", "iç registry · cosign · Trivy"), ("argocd", "Deployment", "GitOps → cluster API'leri"),
                            ("acm", "Deployment", "çoklu cluster")])]
    bottoms = [m + 16] * 3
    for i, (ns, pods) in enumerate(blocks):
        col = i % 3
        bottoms[col] = ns_pods(d, cols[col], bottoms[col], cw, ns, pods, color="mgmt") + 14
    d.note(872, 640, 1300, "Gözlem hattı: kaynak → giriş → depo → arayüz", [
        "Log:   fluent-bit (her node) → egress → mgmt-ingressgw → log-kafka → logstash (ayrıştırma, maskeleme) → elasticsearch → kibana · siem-forwarder",
        "Metrik: prometheus-agent (her cluster) → remote_write → mgmt-ingressgw → thanos-receive → thanos-query → grafana · alertmanager",
        "İz:    Envoy (gateway, waypoint) → OTLP → mgmt-ingressgw → otel-collector (örnekleme) → tempo → grafana (log ↔ iz geçişi)",
        "Güvenlik: k8s audit · WAF · IdP olayları → SIEM (korelasyon, SOAR) · arşiv: worm-archive (Object Lock)",
        "Pilot karşılığı: Loki + Fluent Bit, Prometheus, Tempo (bkz. docs/pilot-architecture.md)"], 12.5)
    d.badge(2172, 900, "out → cluster API :6443 (Argo CD) · sertifika (Vault PKI → istio-csr)", "out", anchor="end")
    d.badge(2172, 926, "in ← bastion / PAM (MFA, oturum kaydı) → arayüzler", "in", anchor="end")
    # akışlar
    d.flow([(420, 112), (420, 150)], "main")
    d.flow([(1500, 112), (1500, 150)], "aux")
    d.note(30, 1040, 1100, "Bu resimde", ["Kimlik zone: DMZ'deki auth-proxy introspection ve token exchange için yalnızca uygulama realm'lerine ulaşır; yönetim kapalı.",
                                          "İç JWT'yi IdP imzalar (anahtar HSM'de); internal JWKS'i doğrulamada kullanır.",
                                          "Mgmt'e giriş tek yönlü: cluster'lar log / metrik / iz yazar, okuyamaz. Arayüzlere yalnızca bastion / PAM'dan.",
                                          "Mgmt'ten çıkış: Argo CD (cluster API), Vault PKI (sertifika), Harbor (image çekme)."], 12.5)
    d.legend(1150, 1040, 1030, [("identity", "kimlik"), ("mgmt", "yönetim"), ("external", "dış")], extra=True, cols=3)
    d.save(out("07-kimlik-yonetim.svg"), "07 · Kimlik ve yönetim / gözlem cluster'ları",
           "Keycloak StatefulSet'i ve yardımcı servisler · gözlem hattı, Vault, registry, GitOps · giriş ve çıkış yönleri", oy=OY)


# =====================================================================================================================
def img08():
    W, H, OY = 2200, 1390, 40
    d = D(W, H)
    d.boundary([(14, 96), (2186, 96), (2186, 990), (14, 990)], "BİR CLUSTER İÇİNDE İKİ NODE (ör. ocp-apps)", "internal", fill_opacity=0.1)
    # Node A
    d.node(30, 130, 1060, 840, "worker-node-1", "RHCOS · CRI-O · kubelet :10250 · OVN-Kubernetes (CNI)")
    d.pod(50, 172, 330, None, "transfer (ns odeme)", "pod", "internal", [("transfer", "app", [":8080 (yalnızca pod ağında)", "Envoy yok, sertifika yok", "istek: http://account-api.hesap:8080"])])
    d.pod(400, 172, 330, None, "notifier (ns bildirim)", "pod", "internal", [("notifier", "app", [":8080", "Kafka tüketici"])])
    d.pod(750, 172, 320, None, "waypoint (ns hesap)", "pod", "dmz", [("istio-proxy (Envoy)", "proxy", ["in :15008 HBONE", "L7: JWT · AuthZ · retry", "metrik :15090"])])
    d.text(50, 330, "DaemonSet'ler (her node'da bir pod)", 14, 700)
    d.pod(50, 344, 520, None, "ztunnel", "DaemonSet · istio-system", "mgmt", [("ztunnel (Rust)", "agent", [
        "in :15008 HBONE (mTLS, HTTP CONNECT) · gelen trafik pod'a :15006 yakalama",
        "out :15001 yakalama: pod'un çıkan trafiği buraya yönlenir",
        "her pod için SPIFFE sertifikası tutar (pod adına mTLS)",
        "L4 AuthorizationPolicy · DNS proxy :15053 · metrik :15020"])], agent=True)
    d.pod(590, 344, 480, None, "istio-cni", "DaemonSet · istio-system", "mgmt", [("install-cni + node agent", "agent", [
        "pod oluşunca pod ağ namespace'ine nftables kuralı yazar",
        "pod trafiği → ztunnel (pod'a ayrıcalık gerekmez)",
        "ztunnel'e pod'un soketini iletir"])], agent=True)
    d.pod(50, 520, 330, None, "fluent-bit", "DaemonSet · logging-agent", "mgmt", [("fluent-bit", "agent", ["/var/log/pods (salt okunur)", "→ mgmt logs (push)"])], agent=True)
    d.pod(400, 520, 330, None, "node-exporter", "DaemonSet · monitoring", "mgmt", [("node-exporter", "agent", [":9100 node metrikleri", "→ prometheus-agent"])], agent=True)
    d.pod(750, 520, 320, None, "edr / falco", "DaemonSet · security", "mgmt", [("sensor", "agent", ["syscall izleme", "→ SIEM"])], agent=True)
    d.box(50, 650, 1020, 96, "Node katmanları", ["RHCOS (değiştirilemez OS) · CRI-O (container çalışma zamanı) · kubelet (pod yaşam döngüsü, :10250)",
                                                 "OVN-Kubernetes: pod ağı + NetworkPolicy (deny-default) · /var/log/pods: container stdout dosyaları",
                                                 "node SSH kapalı; erişim yalnızca oc debug (PAM üzerinden, audit'li)"], color="note")
    d.note(50, 766, 1020, "Pod'dan pod'a istek (numaralar)", [
        "1  transfer, account-api'yi düz HTTP ile çağırır (uygulamanın gözünden hiçbir şey değişmez)",
        "2  istio-cni'nin nftables kuralı bağlantıyı yerel ztunnel'e (:15001) yönlendirir",
        "3  ztunnel: kaynak = transfer'in SPIFFE kimliği; hedefin waypoint'i var → HBONE mTLS :15008 → waypoint",
        "4  waypoint (L7): iç JWT, scope, AuthZ, retry → HBONE → hedef node'un ztunnel'i",
        "5  hedef ztunnel L4 politikası (yalnızca waypoint) → account-api :8080 (pod içi düz)"], 12.5)
    # Node B
    d.node(1110, 130, 1060, 840, "worker-node-2", "aynı DaemonSet'ler")
    d.pod(1130, 172, 330, None, "account-api (ns hesap)", "pod", "internal", [("account-api", "app", [":8080", "yalnızca waypoint'ten gelir"])])
    d.pod(1130, 344, 520, None, "ztunnel", "DaemonSet", "mgmt", [("ztunnel", "agent", ["in :15008 HBONE → pod :8080", "L4: kaynak yalnızca hesap waypoint'i"])], agent=True)
    # Port tablosu
    d.text(1680, 186, "Portlar", 15, 700)
    ports = [(":8080", "uygulama (pod içi)"), (":15001", "ztunnel çıkış yakalama"), (":15006", "ztunnel giriş yakalama"), (":15008", "HBONE (mTLS tüneli)"),
             (":15012", "istiod xDS (mTLS)"), (":15020", "ztunnel / proxy metrik"), (":15021", "sağlık (gateway, waypoint)"), (":15053", "DNS proxy"),
             (":15090", "Envoy metrik"), (":9100", "node-exporter"), (":10250", "kubelet (API sunucusu)")]
    for i, (pt, desc) in enumerate(ports):
        y = 200 + i * 28
        d.n.append(f'<rect x="1680" y="{y}" width="470" height="24" rx="4" fill="{"#f4f7fc" if i % 2 else "#ffffff"}" stroke="#c4c4bf" stroke-width="0.8"/>')
        d.text(1690, y + 17, pt, 12.5, 700)
        d.text(1770, y + 17, desc, 12.5)
    d.box(1130, 520, 1020, 120, "Ambient'te ne değişti?", ["Uygulama pod'unda sidecar (Envoy) yok: pod yalnızca uygulama container'ını taşır.",
                                                            "L4 (mTLS, kimlik, temel izin): node başına ztunnel · L7 (JWT, yol, retry): namespace başına waypoint.",
                                                            "Bir istek: ztunnel → (waypoint) → ztunnel. L7 gerekmeyen trafik waypoint'e uğramaz."], color="note")
    # akışlar
    d.marker(215, 160, 1, "#2f7bd8")
    d.flow([(360, 284), (360, 344)], "main")
    d.marker(378, 318, 2, "#2f7bd8")
    d.flow([(540, 344), (540, 318), (900, 318), (900, 300)], "main", "HBONE :15008 → waypoint", 556, 312)
    d.marker(920, 318, 3, "#2f7bd8")
    d.flow([(1070, 250), (1100, 250), (1100, 420), (1130, 420)], "main")
    d.marker(1100, 300, 4, "#2f7bd8")
    d.flow([(1390, 344), (1390, 300)], "main")
    d.marker(1406, 322, 5, "#2f7bd8")
    d.legend(30, 1010, 2150, [("internal", "uygulama"), ("dmz", "waypoint / gateway"), ("mgmt", "node agent'ları"), ("note", "açıklama")], extra=True, cols=6)
    d.save(out("08-node-anatomisi.svg"), "08 · Bir node'un anatomisi: pod'lar, DaemonSet agent'ları, ztunnel ve HBONE",
           "uygulama pod'unda sidecar yok · trafik node'daki ztunnel'den geçer · L7 kuralları waypoint'te · portlar sağda", oy=OY)


# =====================================================================================================================
def img09():
    W, H, OY = 2200, 1210, 40
    d = D(W, H)
    parts = [("Mobil uygulama", "public"), ("F5 + WAF", "edge"), ("mobile-gw", "dmz"), ("auth-proxy", "dmz"), ("Keycloak", "identity"),
             ("dmz-egressgw", "dmz"), ("int-ingressgw", "internal"), ("mobile-bff", "internal"), ("transfer", "internal"),
             ("account-api", "internal"), ("PostgreSQL", "data"), ("core", "core")]
    x0, dx = 100, 182
    xs = [x0 + i * dx for i in range(len(parts))]
    top, bot = 120, 1000
    for x, (n, c) in zip(xs, parts):
        fill, stroke, tcol = __import__("topo_style").PALETTE[c]
        d.n.append(f'<rect x="{x - 82}" y="{top}" width="164" height="44" rx="8" fill="{fill}" stroke="{stroke}" stroke-width="1.6"/>')
        d.text(x, top + 28, n, 13.5, 700, tcol, "middle")
        d.e.append(f'<line x1="{x}" y1="{top + 44}" x2="{x}" y2="{bot}" stroke="{stroke}" stroke-width="1.4" stroke-dasharray="5 5"/>')
    steps = [(0, 1, "main", "POST /mobile/v1/accounts/1/transfers · :443 TLS 1.3", "DPoP kanıtı + attestation başlıkları · WAF (OWASP), bot, header temizliği"),
             (1, 2, "main", ":443 mTLS (Edge-DMZ CA)", "VIP m-api · istemci sertifikası yalnızca F5"),
             (2, 3, "req", "ext_authz (HBONE → auth waypoint → :8080)", "DPoP: htm/htu/ath, jti tekrarı · attestation · minimum sürüm · kayıtlı cihaz"),
             (3, 4, "req", "introspection + token exchange :443 (egress üzerinden)", "token aktif mi? → iç JWT: 2 dk · acr · scope · sid · aud internal-apis"),
             (4, 3, "ret", "iç JWT (IdP imzalı)", ""),
             (3, 2, "ret", "izin + x-user-jwt", "ret olsaydı: 401 / 403 / 426 burada döner"),
             (2, 5, "main", "/mobile/v1 öneki kaldırılır · Host mobile-bff.internal", "dış token silinir · yalnızca iç JWT taşınır"),
             (5, 6, "main", "zone geçişi :443 mTLS (ISTIO_MUTUAL)", "kaynak kimliği = dmz-egressgw · iç JWT imzası (JWKS)"),
             (6, 7, "main", "HBONE → channel-bff waypoint → mobile-bff", "channel=mobile · issuer = customers realm"),
             (7, 8, "main", "HBONE → odeme waypoint → transfer :8080", "scope transfers:write · acr ≥ 2 (son 5 dk) · step-up gerekirse 401"),
             (8, 9, "req", "GET bakiye · sahiplik (hesap waypoint)", "BOLA: hesap bu kullanıcının mı?"),
             (9, 8, "ret", "200", ""),
             (8, 10, "main", "INSERT transfer + outbox · :15432 → data :5432 (mTLS)", "int-egressgw üzerinden · kısa ömürlü DB kullanıcısı (Vault)"),
             (8, 11, "main", "posting · core-adapter → core-ingressgw :443", "idempotency anahtarı · saga"),
             (8, 0, "ret", "202 Accepted (referans) · tüm hop'lar aynı request_id / trace_id", "olay: outbox → Kafka → bildirim (push)")]
    y = top + 84
    for i, (a, b, kind, lab, sub) in enumerate(steps):
        xa, xb = xs[a], xs[b]
        kk = "aux" if kind == "ret" else kind
        d.flow([(xa, y), (xb, y)], kk)
        mx = min(xa, xb)
        d.marker(mx + 2, y - 18, i + 1, "#2f7bd8" if kind == "main" else ("#5f5f5a" if kind == "ret" else "#c2410c"))
        d.text(mx + 22, y - 12, lab, 12.5, 600)
        if sub:
            d.text(mx + 22, y + 14, sub, 11.5, 400, "#5f5f5a")
        y += 54
    d.note(40, 1030, 1050, "Nasıl okunur", ["Sütunlar istekten geçen bileşenler (renk = zone), yukarıdan aşağı zaman.",
                                             "Mavi: mTLS ana akış · turuncu: kontrol / yardımcı çağrı · gri kesikli: yanıt.",
                                             "Her satırın altında o adımda yapılan kontrol. Ayrıntılar: DMZ 02-03, internal 04-05, veri 06, kimlik 07, node 08."], 12.5)
    d.legend(1110, 1030, 1070, [("public", "internet"), ("edge", "edge"), ("dmz", "DMZ"), ("identity", "kimlik"), ("internal", "internal"),
                               ("data", "veri"), ("core", "core")], extra=False, cols=4)
    d.save(out("09-uctan-uca-mobil-transfer.svg"), "09 · Uçtan uca istek: mobil uygulamadan para transferi, adım adım",
           "her adım: kimden → kime · port / protokol · yapılan kontrol · bir isteğin bütün zone'lardaki yolculuğu", oy=OY)


IMAGES = {"00": img00, "01": img01, "02": img02, "03": img03, "04": img04, "05": img05, "06": img06, "07": img07, "08": img08, "09": img09}

if __name__ == "__main__":
    for k in (sys.argv[1:] or IMAGES):
        IMAGES[k]()
        print("ok", k)
