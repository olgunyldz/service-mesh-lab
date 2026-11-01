"""Özet zone mimarisi: güven kademeleri ve kanalların giriş yolları (ayrıntı: topo_prod_full.py).
Çalıştırma: python docs/images/src/zone_ozet.py  (SVG üretir; PNG için README.md'deki komut)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from topo_style import Diagram, PALETTE

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "zone-ozet.svg")
OY = 50
W, H = 1560, 1610
d = Diagram(W, H)

# Sütunlar: sol (internet yolu), orta (şube), sağ (ATM/POS, PCI, kimlik, çıkış), en sağ (dış dünya)
LX0, LX1 = 40, 760
MX0, MX1 = 790, 1010
RX0, RX1 = 1040, 1320
EX0, EX1 = 1366, 1534

# ---------------- Güven sınırları
d.boundary([(20, 88), (770, 88), (770, 204), (20, 204)], "İNTERNET · GÜVENİLMEYEN AĞ", "public", fill_opacity=0.55)
d.boundary([(780, 88), (1330, 88), (1330, 204), (780, 204)], "KURUM WAN · ÖZEL AĞ", "wan", fill_opacity=0.7)
d.boundary([(14, 382), (1338, 382), (1338, 1396), (14, 1396)], "BANKA PERİMETRESİ", "external")
d.boundary([(1030, 568), (1330, 568), (1330, 734), (1030, 734)], "PCI DSS", "pci", label_at=(1220, 555))
d.boundary([(28, 762), (1330, 762), (1330, 1046), (1030, 1046), (1030, 1184), (1330, 1184), (1330, 1388), (28, 1388)],
           "PRIVATE ZONE · İNTERNETE KAPALI", "internal", label_at=(330, 749))
d.boundary([(1352, 560), (1548, 560), (1548, 1200), (1352, 1200)], "DIŞ DÜNYA", "external", fill_opacity=0.6)

# ---------------- Kanallar
d.channel(LX0, 110, LX1 - LX0, "Mobil · Web · Partner", "m-api · ib · api.banka.com.tr")
d.channel(MX0, 110, MX1 - MX0, "Şube", "SD-WAN / MPLS")
d.channel(RX0, 110, RX1 - RX0, "ATM · POS", "özel ATM ağı · acquirer")

# ---------------- Zone'lar
d.zone(LX0, 250, LX1 - LX0, 100, "Sağlayıcı katmanı (banka dışı)", ["DDoS scrubbing · CDN · bot yönetimi"], center=True, color="external")
d.zone(LX0, 400, LX1 - LX0, 100, "Dış DMZ · edge", ["GSLB · F5 LB + WAF · kanal başına VIP ve sertifika"], center=True, color="edge")
d.zone(MX0, 400, MX1 - MX0, 160, "Şube zone", ["SD-WAN hub", "branch-fw", "branch-gw (A/B)", "AD SSO · cihaz sert."], color="wan")
d.zone(RX0, 400, RX1 - RX0, 130, "ATM · POS ağı", ["atm-fw · pos-fw · APN", "terminal sertifikası", "ISO 8583 · NDC/DDC"], color="wan")
d.zone(LX0, 550, LX1 - LX0, 140, "İç DMZ · ocp-dmz (DC1/DC2)", ["kanal başına namespace: web · mobile · partner",
       "auth-service (token exchange) · ratelimit · egress gw"], center=True, color="dmz")
d.zone(RX0, 580, RX1 - RX0, 140, "Kart zone · ocp-pci", ["ATM / POS switch · HSM", "tokenization · kart DB", "ayrı cluster ve segment"], color="pci")

d.zone(LX0, 780, MX1 - LX0, 220, "Internal zone · ocp-apps (modern mikroservisler)", title_above=True, color="internal")
d.ns(65, 835, MX1 - 25 - 65, 60, "int-ingressgw · MUTUAL TLS · iç JWT doğrulama · deny-by-default", [], color="internal")
d.ns(65, 912, 450, 70, "ocp-apps · DC1", ["domain namespace'leri · core-adapter"], color="internal")
d.ns(535, 912, 450, 70, "ocp-apps · DC2", ["domain namespace'leri · core-adapter"], color="internal")
d.zone(RX0, 780, RX1 - RX0, 150, "Kimlik zone", ["Keycloak / RHBK (A/B)", "AD · MFA · consent", "redis-session"], color="identity")

d.zone(LX0, 1030, MX1 - LX0, 100, "Core banking zone (legacy) · ocp-core / VM", ["core-app · ledger · eod-batch · yalnızca core-adapter'dan"],
       center=True, color="core")
d.zone(RX0, 1062, RX1 - RX0, 108, "Dış çıkış zone", ["outbound NGFW · proxy", "kurum hatları (VPN)"], color="egress")
d.zone(LX0, 1160, MX1 - LX0, 116, "Veri zone (DC1 ⇄ DC2)", ["Oracle · MSSQL · PostgreSQL · Kafka · RabbitMQ · Valkey", "ocp-apps'ten int-egressgw ile (mTLS) · core'dan doğrudan"], center=True, color="data")
d.zone(LX0, 1290, RX1 - LX0, 90, "Yönetim ve gözlem · SOC", ["ELK · Prometheus/Thanos · Grafana · Tempo · SIEM/SOAR · CI/CD · Vault · PAM · tüm zone'lardan tek yönlü log"],
       center=True, color="mgmt")

# ---------------- Dış dünya
d.box(EX0, 600, EX1 - EX0, 110, "Kart şemaları", ["Visa · MC · TROY", "BKM · özel hat"], color="external", fill="#ffffff")
d.box(EX0, 1040, EX1 - EX0, 140, "Kurumlar · servisler", ["EFT/FAST · SWIFT", "KKB · SMS · push", "e-posta · SaaS"], color="external", fill="#ffffff")

# ---------------- Oklar
d.arrow([(400, 188), (400, 250)], label="internet · 443", lx=412, ly=226)
d.arrow([(400, 350), (400, 400)], label="dış firewall", lx=412, ly=370)
d.arrow([(400, 500), (400, 550)], label="iç firewall · yalnızca 443", lx=412, ly=530)
d.arrow([(300, 690), (300, 835)], blue=True, label="mTLS + iç JWT", lx=312, ly=730)
d.arrow([(900, 188), (900, 400)], label="MPLS", lx=912, ly=300)
d.arrow([(900, 560), (900, 835)], blue=True, label="mTLS + iç JWT", lx=912, ly=640)
d.arrow([(1180, 188), (1180, 400)], label="özel hat", lx=1192, ly=300)
d.arrow([(1180, 530), (1180, 580)])
d.arrow([(RX0, 650), (1022, 650), (1022, 880), (MX1 - 25, 880)], blue=True)
d.vt(1015, 765, "mTLS · token PAN", 13.5, "#1f1f1f", 600)
d.arrow([(LX1, 650), (776, 650), (776, 744), (1250, 744), (1250, 780)], dashed=True)
d.t(1062, 758, "OIDC · JWKS (auth-service)", 13, 400, "#5f5f5a", layer=d.l)
d.arrow([(300, 982), (300, 1030)], blue=True, label="core-adapter · mTLS", lx=312, ly=1012)
d.arrow([(300, 1130), (300, 1160)], label="TLS", lx=312, ly=1150)
d.arrow([(MX1, 950), (1026, 950), (1026, 1120), (RX0, 1120)], blue=True)
d.vt(1019, 1040, "int-egressgw", 13.5, "#1f1f1f", 600)
d.arrow([(RX1, 1110), (EX0, 1110)])
d.arrow([(RX1, 650), (EX0, 650)], dashed=True)

# ---------------- Lejant
ly = 1440
items = [("public", "internet"), ("wan", "kurum WAN"), ("edge", "edge"), ("dmz", "DMZ"), ("pci", "PCI"), ("internal", "internal"),
         ("core", "core"), ("data", "veri"), ("identity", "kimlik"), ("egress", "dış çıkış"), ("mgmt", "yönetim"), ("external", "banka dışı")]
for i, (k, label) in enumerate(items):
    x = 40 + (i % 6) * 250
    y = ly + (i // 6) * 32
    fill, stroke, _ = PALETTE[k]
    d.n.append(f'<rect x="{x}" y="{y}" width="30" height="18" rx="4" fill="{fill}" stroke="{stroke}" stroke-width="1.6"/>')
    d.t(x + 40, y + 14, label, 14.5)
y = ly + 70
d.n.append(f'<line x1="40" y1="{y + 6}" x2="80" y2="{y + 6}" stroke="#2f7bd8" stroke-width="3"/>')
d.t(92, y + 11, "zone geçişi (mTLS; internal'a iç JWT ile)", 14.5)
d.n.append(f'<line x1="520" y1="{y + 6}" x2="560" y2="{y + 6}" stroke="#b3b3ad" stroke-width="1.8" stroke-dasharray="6 5"/>')
d.t(572, y + 11, "yardımcı akış", 14.5)
d.n.append(f'<line x1="800" y1="{y + 6}" x2="840" y2="{y + 6}" stroke="#6d9fe4" stroke-width="3" stroke-dasharray="14 8"/>')
d.t(852, y + 11, "güven sınırı · ayrıntı: topology-prod-full", 14.5)

d.save(OUT, "Zone özeti: internete yalnızca edge bakar; her kanal internal'a mTLS ile girer",
       "Aşağı indikçe güven artar · 2 DC aktif-aktif · ATM/POS internetten değil özel ağdan PCI'ya · dışarıya yalnızca dış çıkış zone'undan", oy=OY)
print("ok", OUT)
