"""Banka prod topolojisi (hedef), ayrıntılı: kanal -> zone -> cluster -> domain namespace -> veri -> dış çıkış.
Renk = güven seviyesi; kalın kesikli çizgiler = güven sınırları (internet, kurum WAN'ı, banka perimetresi, private zone, PCI).
Çalıştırma: python docs/images/src/topo_prod_full.py  (SVG üretir; PNG için README.md'deki komut)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from topo_style import Diagram, PALETTE

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "topology-prod-full.svg")
OY = 50                       # başlık altında sınır etiketleri için boşluk
W, H = 2630, 3175
d = Diagram(W, H)

L0, L1 = 40, 1460            # sol alan (internet yolu, internal, core, data)
R0, R1 = 1500, 2160          # sağ alan (özel ağlar, kart, kimlik, çıkış)
IX0, IW = 65, 1370           # sol zone'ların iç alanı
RX0, RW = 1525, 610          # sağ zone'ların iç alanı
X0, X1 = 2244, 2584          # dış dünya sütunu


def grid(n, i, x0=IX0, w=IW, gap=20):
    bw = (w - gap * (n - 1)) / n
    return x0 + i * (bw + gap), bw


# =============================== Güven sınırları (en altta çizilir)
d.boundary([(20, 88), (1476, 88), (1476, 204), (20, 204)], "İNTERNET · GÜVENİLMEYEN AĞ", "public", fill_opacity=0.55)
d.boundary([(1484, 88), (2192, 88), (2192, 204), (1484, 204)], "KURUM WAN · ÖZEL AĞ (İNTERNETTEN AYRI)", "wan", fill_opacity=0.7)
d.boundary([(14, 232), (2204, 232), (2204, 2952), (14, 2952)], "BANKA PERİMETRESİ", "external")
d.boundary([(28, 1022), (2192, 1022), (2192, 1348), (1490, 1348), (1490, 1714), (2192, 1714), (2192, 2944), (28, 2944)],
           "PRIVATE ZONE · İNTERNETE KAPALI · YALNIZCA GATEWAY'LERDEN", "internal", label_at=(1640, 1006))
d.boundary([(1490, 530), (2170, 530), (2170, 980), (1490, 980)], "PCI DSS KAPSAMI · AYRI SEGMENT", "pci", label_at=(1830, 517))
d.boundary([(2224, 520), (2610, 520), (2610, 1990), (2224, 1990)], "DIŞ DÜNYA · ÇIKIŞ HEDEFLERİ", "external", fill_opacity=0.6)

# =============================== Kanallar
for i, (t, sub) in enumerate([("Web", "ib.banka.com.tr"), ("Mobil", "m-api.banka.com.tr"), ("Partner · açık bankacılık", "api.banka.com.tr · TPP")]):
    x, w = grid(3, i, L0, L1 - L0)
    d.channel(x, 110, w, t, sub)
d.channel(1500, 110, 210, "Şube", "SD-WAN / MPLS")
d.channel(1725, 110, 210, "ATM", "özel ATM ağı")
d.channel(1950, 110, 210, "POS", "acquirer · APN")

# =============================== Internet edge
d.zone(L0, 250, L1 - L0, 240, "Internet Edge · ortak (DC1/DC2)", right="kanal başına VIP · sertifika · WAF politikası", title_above=True, color="edge")
edge = [("DDoS koruma", ["ISS + bulut scrubbing", "BGP anycast", "L3/L4 hacim saldırısı"]),
        ("GSLB / DNS", ["DC1 ⇄ DC2 aktif-aktif", "sağlık kontrolü · DNSSEC", "coğrafi yönlendirme"]),
        ("Perimeter NGFW", ["yalnızca 443/TCP", "IPS · geo-IP · itibar", "DC başına HA çift"]),
        ("F5 LTM + Advanced WAF", ["VIP: ib · m-api · api · auth", "TLS 1.3 · anahtar HSM'de", "partner: mTLS · bot koruma", "header temizliği · 5xx maske"])]
for i, (t, ls) in enumerate(edge):
    x, w = grid(4, i)
    d.box(x, 305, w, 160, t, ls, color="edge", fill="#ffffff")
for i in range(3):
    x, w = grid(4, i)
    d.arrow([(x + w, 385), (x + w + 20, 385)])

# =============================== Şube ve ATM/POS ağları
d.zone(1500, 250, 210, 240, "Şube zone", ["SD-WAN hub", "branch-fw (NGFW)", "branch-gw (A/B)", "NAC · cihaz sert.", "çağrı merkezi ·", "back-office"], color="wan")
d.zone(1725, 250, 435, 240, "ATM · POS ağı", ["atm-fw · pos-fw · APN gateway", "terminal / cihaz sertifikası", "ISO 8583 · NDC/DDC (TLS)", "TID / MID izin listesi", "internet edge'inden geçmez"], color="wan")

# =============================== DMZ
d.firewall(L0, 494, L1 - L0, 22, "İÇ FIREWALL (farklı üretici) · yalnızca F5 → DMZ :443", tx=300)
d.zone(L0, 540, L1 - L0, 430, "DMZ zone · ocp-dmz (DC1/DC2) · kanal başına namespace · iş mantığı yok", right="açık bankacılık büyürse: ayrı partner DMZ cluster'ı", title_above=True, color="dmz")
dmz_a = [("ns edge-web", ["web-static (SPA) · CSP · CORS", "web-token-handler: cookie ↔ token", "HttpOnly · SameSite · CSRF", "CIBA / QR onay akışı"]),
         ("ns edge-mobile", ["mobile-gw · DPoP doğrulama", "attestation · minimum sürüm", "cihaz bağlama (device_id)", "x-channel=mobile · local kota"]),
         ("ns edge-partner", ["FAPI 2.0 · PAR · private_key_jwt", "mTLS ↔ token bağı (RFC 8705)", "consent kontrolü · izin listesi", "geliştirici portalı · sandbox"])]
dmz_b = [("ns istio-egress · internal'a tek kapı", ["dmz-egressgw → yalnızca channel-bff", "port + kimlik AuthZ · mTLS", "dış token silinir; iç JWT taşınır", "OCSP / CRL (→ dış çıkış)"]),
         ("ns auth · auth-proxy", ["ext_authz: her kanal, her istek", "opak dış token → IdP introspection", "RFC 8693 → iç JWT (IdP imzalar)", "≤ 2 dk · acr · scope · device_id · sid"]),
         ("ns ratelimit · edge-cache", ["global kota (partner, kullanıcı)", "dmz-redis: sayaç · DPoP jti", "fail-open; local kota korur", "kota aşımı: 429"])]
for i, (t, ls) in enumerate(dmz_a):
    x, w = grid(3, i)
    d.ns(x, 600, w, 150, t, ls, color="dmz")
for i, (t, ls) in enumerate(dmz_b):
    x, w = grid(3, i)
    d.ns(x, 790, w, 150, t, ls, color="dmz")
wx, ww = grid(3, 0); mx, mw = grid(3, 1); px, pw = grid(3, 2)
d.arrow([(wx + ww / 2, 750), (wx + ww / 2, 790)])
d.arrow([(mx + 40, 750), (mx + 40, 770), (wx + ww - 60, 770), (wx + ww - 60, 790)])
d.arrow([(px + 40, 750), (px + 40, 778), (wx + ww - 30, 778), (wx + ww - 30, 790)])
d.arrow([(mx + mw / 2, 750), (mx + mw / 2, 790)], dashed=True, label="ext_authz", lx=mx + mw / 2 + 8, ly=772)
d.arrow([(px + pw / 2 + 40, 750), (px + pw / 2 + 40, 790)], dashed=True, label="kota", lx=px + pw / 2 + 48, ly=772)

# =============================== Kart zone (PCI)
d.zone(R0, 540, R1 - R0, 430, "Kart zone · PCI DSS · ocp-pci (ayrı cluster)", color="pci")
pci = [("ns atm", ["atm-switch (NDC/DDC)", "ATM izleme · nakit yönetimi", "PIN doğrulama → HSM"]),
       ("ns pos", ["pos-switch (ISO 8583)", "acquiring · sanal POS", "3DS ACS · terminal yönetimi"]),
       ("ns card · iso8583-adapter", ["kart yönetimi · tokenization", "iso8583-adapter: REST ↔ ISO 8583", "yalnızca /cards/**, /authorizations/**", "stand-in (core kapalıyken onay)"]),
       ("HSM · şema bağlantıları", ["payShield HSM (PIN, CVV) · RKL", "şema bağlantısı (özel hat)", "takas · mutabakat", "kart DB: Oracle (TDE)"])]
for i, (t, ls) in enumerate(pci):
    x, w = grid(2, i % 2, RX0, RW)
    d.ns(x, 600 if i < 2 else 790, w, 150, t, ls, color="pci")

# =============================== Internal (modern mikroservisler)
d.zone(L0, 1040, L1 - L0, 660, "Internal zone · ocp-apps (DC1/DC2) · modern mikroservisler · domain bazlı namespace", title_above=True, color="internal")
d.ns(IX0, 1100, IW, 95, "ns istio-ingress · int-ingressgw (MUTUAL TLS)",
     ["AuthZ: yalnızca dmz-egressgw, branch-gw ve kart zone kimlikleri → channel-bff · RequestAuthentication: iç JWT (Keycloak JWKS, ≤ 2 dk)",
      "her domain namespace'inde waypoint (acr · scope · rol · sub ile L7 yetki) · ztunnel: mTLS, L4 varsayılan reddet · imzalı image"], color="internal")
dom = [("ns channel-bff", ["mobile-bff · web-bff · branch-bff", "kanal başına toplama (aggregation)", "iç JWT'yi domain'e iletir"]),
       ("ns hesap", ["account · statement", "waypoint: rol + sub (BOLA)", "PostgreSQL (servis başına DB)"]),
       ("ns odeme", ["transfer · eft-fast · orkestrasyon", "saga · idempotency · step-up", "Kafka: payment-events"]),
       ("ns kart", ["card-api (yalnızca token PAN)", "limit · kampanya", "→ kart zone (tokenization)"]),
       ("ns kredi", ["kredi başvuru · skorlama", "KKB sorgusu (egress)", "RabbitMQ: legacy onay akışı"]),
       ("ns musteri", ["customer · kyc · onboarding", "e-imza · NFC kimlik", "MSSQL CRM (legacy) okuma"]),
       ("ns security", ["tx-signing-svc (işlem imzası)", "fraud: Kafka Streams · kural + ML", "işlem öncesi karar · step-up"]),
       ("ns bildirim", ["SMS · push · e-posta", "RabbitMQ / Kafka tüketici", "→ dış çıkış (SMS/push gw)"]),
       ("ns integration", ["core-adapter (anti-corruption)", "kurum: EFT/FAST · SWIFT · KKB", "strangler: kademeli taşıma"]),
       ("ns raporlama", ["ekstre · dekont üretimi", "batch (CronJob)", "→ veri ambarı (CDC)"]),
       ("ns olay", ["outbox → Kafka (Debezium)", "Schema Registry · Avro", "olay tabanlı entegrasyon"]),
       ("ns istio-egress", ["int-egressgw (port + kimlik)", "→ core · data · dış çıkış", "mTLS · REGISTRY_ONLY"])]
for i, (t, ls) in enumerate(dom):
    x, w = grid(4, i % 4)
    d.ns(x, 1225 + (i // 4) * 158, w, 130, t, ls, color="internal")
for i in range(4):
    x, w = grid(4, i)
    d.arrow([(x + w / 2, 1195), (x + w / 2, 1225)])

# =============================== Sağ: kimlik, dış çıkış
d.zone(R0, 1040, R1 - R0, 290, "Kimlik zone", ["keycloak / RHBK (A/B)", "realm: müşteri · partner · personel", "AD / LDAP federasyonu (personel)",
       "MFA · step-up (acr) · brute force", "device-registry · consent-svc", "token exchange (RFC 8693) → iç JWT ≤ 2 dk",
       "introspection · JWKS (internal doğrular)", "redis-session · PostgreSQL HA · HSM"], color="identity")
d.zone(R0, 1360, R1 - R0, 340, "Dış çıkış zone (outbound DMZ)", ["outbound NGFW · hedef izin listesi", "forward proxy / SWG (TLS inceleme)",
       "kurum hatları: VPN / kiralık hat", "SMTP relay · SMS / push gateway", "giriş: yalnızca egress gateway'ler", "DNS: yalnızca iç resolver"], color="egress")

# =============================== Core banking (legacy)
d.zone(L0, 1740, L1 - L0, 270, "Core banking zone (legacy) · ocp-core / VM (DC1/DC2) · ayrı cluster", right="strangler: kademeli taşıma", title_above=True, color="core")
core = [("core-ingressgw (MUTUAL TLS)", ["yalnızca core-adapter kimliği", "mTLS · L7 yetki", "tek giriş noktası"]),
        ("core-app (Java EE / COBOL)", ["ledger · posting engine", "mevduat · kredi · döviz", "WebLogic / konteyner"]),
        ("eod-batch", ["gün sonu · faiz tahakkuku", "mutabakat · raporlar", "pencere: 23:00 - 02:00"]),
        ("entegrasyon", ["RabbitMQ (legacy kuyruklar)", "IBM MQ köprüsü", "CDC: Debezium → Kafka"])]
for i, (t, ls) in enumerate(core):
    x, w = grid(4, i)
    d.box(x, 1800, w, 180, t, ls, color="core", fill="#ffffff")
d.zone(R0, 1740, R1 - R0, 270, "İş sürekliliği", ["DC1 ⇄ DC2 aktif-aktif", "Oracle Data Guard (sync, RPO ≈ 0)", "Kafka MirrorMaker2 · CNPG replika",
       "RTO < 1 saat · yıllık DR tatbikatı"], color="note")

# =============================== Data
d.zone(L0, 2050, L1 - L0, 420, "Data zone · ocp-data + VM (DC1 ⇄ DC2 replikasyon)", title_above=True, color="data")
data = [("Oracle RAC", ["core DB · Data Guard", "TDE · RMAN yedek", "erişim: core-app + CDC"]),
        ("RabbitMQ", ["quorum queues (3 node)", "legacy entegrasyon", "TLS · vhost başına kullanıcı"]),
        ("MSSQL Always On", ["legacy: CRM · raporlama", "AG listener · TDE", "okuma replikası → DWH"]),
        ("Kafka (Strimzi)", ["3 broker · KRaft", "MirrorMaker2 DC1 → DC2", "ACL · topic başına yetki"]),
        ("Valkey / Redis", ["önbellek · oturum", "ACL · önek bazlı", "replika (A/B)"]),
        ("Nesne depolama", ["ODF / MinIO (S3)", "doküman · dekont", "yaşam döngüsü politikası"]),
        ("Yedek", ["RMAN · pgBackRest · Velero", "immutable (WORM) · şifreli", "geri dönüş testi"]),
        ("PostgreSQL (CloudNativePG)", ["servis başına DB ve kullanıcı", "sync replika · PITR", "yalnızca kendi servisi"])]
for i, (t, ls) in enumerate(data):
    x, w = grid(4, i % 4)
    d.ns(x, 2110 if i < 4 else 2290, w, 150, t, ls, color="data")
d.zone(R0, 2050, R1 - R0, 420, "Veri ambarı · analitik", ["CDC (Debezium) · ETL", "DWH (Exadata / Teradata)", "BI: Power BI · Tableau",
       "maskeli veri → test ortamları", "KVKK: anonimleştirme", "erişim: rol bazlı, loglanır"], color="data")

# =============================== Yönetim ve gözlem
d.zone(L0, 2520, R1 - L0, 410, "Yönetim ve gözlem · ocp-mgmt (DC1/DC2)", right="tüm cluster'lar: log, metrik ve iz → mgmt", title_above=True, color="mgmt")
mg = [("Loglar · ELK", ["fluent-bit (her node)", "→ Kafka (log topic)", "→ Logstash → Elasticsearch", "→ Kibana · maskeleme"]),
      ("Metrik", ["Prometheus (agent)", "→ Thanos (uzun saklama)", "Grafana · Alertmanager", "SLO panoları"]),
      ("İz (tracing)", ["OpenTelemetry Collector", "→ Grafana Tempo", "trace ↔ log ↔ metrik", "x-request-id · traceparent"]),
      ("Mesh", ["Kiali (çoklu cluster)", "istiod (cluster başına)", "mTLS · politika görünümü", "trafik grafiği"]),
      ("SIEM / SOAR", ["QRadar / Splunk", "k8s audit · DB audit", "WORM arşiv · NTP (zaman)", "korelasyon · SOAR"]),
      ("Olay yönetimi", ["Opsgenie / PagerDuty", "ITSM (ServiceNow)", "nöbet · runbook", "olay sonrası analiz"]),
      ("CI/CD", ["GitLab CI / Jenkins", "SAST · SCA · Trivy", "SBOM (Syft)", "gitleaks · SonarQube"]),
      ("Registry", ["Harbor (iç registry)", "cosign imza · SBOM", "zafiyet taraması", "upstream proxy (çıkış)"]),
      ("GitOps", ["Argo CD", "ACM (çoklu cluster)", "ortam promosyonu", "drift tespiti"]),
      ("Secret · PKI", ["Vault + HSM", "dinamik DB kimlikleri", "cert-manager · istio-csr", "Transit (imza, şifre)"]),
      ("Erişim", ["bastion · VDI → API :6443", "PAM (CyberArk)", "MFA · oturum kaydı", "just-in-time yetki"]),
      ("Politika · uyum", ["Kyverno / Gatekeeper", "Compliance Operator", "CIS · PCI denetimi", "imzasız image reddi"])]
for i, (t, ls) in enumerate(mg):
    x, w = grid(6, i % 6, IX0, R1 - 25 - IX0)
    d.ns(x, 2575 if i < 6 else 2750, w, 156, t, ls, color="mgmt")

# =============================== Dış dünya (perimetre dışı)
d.box(X0, 600, X1 - X0, 170, "Kart şemaları", ["Visa · Mastercard · TROY", "BKM takas · mutabakat", "özel hat (kiralık devre)"], color="external", fill="#ffffff")
d.box(X0, 1380, X1 - X0, 200, "Dış kurumlar", ["TCMB: EFT · FAST", "SWIFT (ISO 20022)", "KKB · GİB · MERNİS / KPS", "partner bankalar"], color="external", fill="#ffffff")
d.box(X0, 1610, X1 - X0, 200, "İnternet servisleri", ["SMS sağlayıcı · APNs / FCM", "e-posta (SMTP relay)", "SaaS: OCR · e-imza · harita", "yazılım güncellemeleri"], color="external", fill="#ffffff")

# =============================== Oklar
for i in range(3):
    x, w = grid(3, i, L0, L1 - L0)
    d.arrow([(x + w / 2, 188), (x + w / 2, 250)])
f5x, f5w = grid(4, 3)
d.arrow([(f5x + f5w / 2, 465), (f5x + f5w / 2, 528), (wx + ww / 2, 528), (wx + ww / 2, 600)])
d.arrow([(mx + mw / 2, 528), (mx + mw / 2, 600)])
d.arrow([(f5x + f5w / 2, 528), (px + pw / 2, 528), (px + pw / 2, 600)], label="mTLS (Edge-DMZ CA)", lx=f5x + f5w / 2 + 10, ly=483)
d.arrow([(1605, 188), (1605, 250)])
d.arrow([(1830, 188), (1830, 250)])
d.arrow([(2055, 188), (2055, 250)])
d.arrow([(1942, 490), (1942, 540)])
# DMZ -> internal
d.firewall(L0, 978, 1456, 24, "INTERNAL FIREWALL · yalnızca gateway'ler → int-ingressgw :443", tx=860)
d.arrow([(wx + ww / 2, 940), (wx + ww / 2, 1100)], blue=True, label="mTLS + iç JWT (IdP)", lx=wx + ww / 2 + 12, ly=962)
# şube -> internal (şerit 1488), kart -> internal (şerit 1474)
d.arrow([(1500, 380), (1488, 380), (1488, 1135), (IX0 + IW, 1135)], blue=True)
d.vt(1481, 760, "şube: mTLS + iç JWT", 14, "#1f1f1f", 600)
d.arrow([(1500, 870), (1474, 870), (1474, 1170), (IX0 + IW, 1170)], blue=True)
d.vt(1467, 1060, "kart: token PAN", 14, "#1f1f1f", 600)
# auth -> kimlik
d.arrow([(mx + mw / 2 + 80, 940), (mx + mw / 2 + 80, 1031), (1580, 1031), (1580, 1040)], dashed=True)
d.t(mx + mw / 2 + 92, 962, "auth-proxy → IdP: introspection · token exchange", 14, 400, "#5f5f5a", layer=d.l)
# kart -> şemalar (özel hat, perimetre dışına)
d.arrow([(R1, 690), (X0, 690)], dashed=True, label="özel hat", lx=2170, ly=680)
# internal -> core, data, dış çıkış
cax, caw = grid(4, 0)
d.arrow([(cax + caw / 2, 1671), (cax + caw / 2, 1800)], blue=True, label="mTLS", lx=cax + caw / 2 + 12, ly=1728)
egx, egw = grid(4, 3)
d.arrow([(egx + egw, 1610), (1448, 1610), (1448, 2365), (IX0 + IW, 2365)], blue=True)
d.vt(1441, 1880, "PostgreSQL · Kafka · Valkey · RabbitMQ (mTLS)", 14, "#1f1f1f", 600)
d.arrow([(egx + egw, 1650), (R0, 1650)], blue=True)
d.t(1525, 1688, "← int-egressgw (yalnızca buradan çıkılır)", 14, 600, "#1f1f1f", layer=d.l)
# dış çıkış -> dış dünya
d.arrow([(R1, 1480), (X0, 1480)], label="VPN / hat", lx=2168, ly=1470)
d.arrow([(R1, 1560), (2200, 1560), (2200, 1710), (X0, 1710)], label="proxy", lx=2212, ly=1640)
# mgmt -> dış çıkış (CI/CD, registry upstream proxy)
d.arrow([(R1, 2600), (2186, 2600), (2186, 1690), (R1, 1690)], dashed=True)
d.vt(2179, 2150, "CI/CD · registry upstream (proxy)")
# core -> data
c1x, c1w = grid(4, 1); c2x, c2w = grid(4, 2); c3x, c3w = grid(4, 3)
o0x, o0w = grid(4, 0); o1x, o1w = grid(4, 1)
d.arrow([(c1x + 60, 1980), (c1x + 60, 2025), (o0x + o0w / 2, 2025), (o0x + o0w / 2, 2110)], label="Oracle", lx=o0x + o0w / 2 + 8, ly=2040)
d.arrow([(c2x + c2w / 2, 1980), (c2x + c2w / 2, 2110)], label="raporlama", lx=c2x + c2w / 2 + 8, ly=2070)
d.arrow([(c3x + 60, 1980), (c3x + 60, 2035), (o1x + o1w / 2, 2035), (o1x + o1w / 2, 2110)])
d.arrow([(c3x + c3w / 2 + 40, 1980), (c3x + c3w / 2 + 40, 2110)], dashed=True, label="CDC", lx=c3x + c3w / 2 + 48, ly=2070)
# data -> veri ambarı
d.arrow([(IX0 + IW, 2400), (R0, 2400)], dashed=True)
d.t(1525, 2440, "← CDC · ETL (Oracle, MSSQL, Kafka)", 14, 400, "#5f5f5a", layer=d.l)

# =============================== Lejant
ly = 2985
d.t(40, ly, "Gösterim", 17, 600)
items = [("public", "internet (güvenilmeyen)"), ("wan", "kurum WAN · özel ağ"), ("edge", "edge"), ("dmz", "DMZ"), ("egress", "dış çıkış"),
         ("pci", "PCI (kart verisi)"), ("internal", "internal (private)"), ("core", "core banking"), ("data", "veri"),
         ("identity", "kimlik"), ("mgmt", "yönetim"), ("external", "perimetre / dış dünya")]
for i, (k, label) in enumerate(items):
    x = 40 + (i % 6) * 360
    y = ly + 24 + (i // 6) * 34
    fill, stroke, _ = PALETTE[k]
    d.n.append(f'<rect x="{x}" y="{y}" width="34" height="20" rx="5" fill="{fill}" stroke="{stroke}" stroke-width="1.6"/>')
    d.t(x + 46, y + 15, label, 15)
y = ly + 24 + 2 * 34
legend_lines = [("blue", "ana akış (mTLS; zone geçişinde iç JWT)"), ("gray", "istek akışı"), ("dash", "yardımcı akış (ext_authz, CDC, proxy, şema hattı)"),
                ("bound", "güven sınırı (kalın kesikli)")]
for i, (k, label) in enumerate(legend_lines):
    x = 40 + i * 540
    if k == "blue":
        d.n.append(f'<line x1="{x}" y1="{y + 10}" x2="{x + 40}" y2="{y + 10}" stroke="#2f7bd8" stroke-width="3"/>')
    elif k == "gray":
        d.n.append(f'<line x1="{x}" y1="{y + 10}" x2="{x + 40}" y2="{y + 10}" stroke="#b3b3ad" stroke-width="1.8"/>')
    elif k == "dash":
        d.n.append(f'<line x1="{x}" y1="{y + 10}" x2="{x + 40}" y2="{y + 10}" stroke="#b3b3ad" stroke-width="1.8" stroke-dasharray="6 5"/>')
    else:
        d.n.append(f'<line x1="{x}" y1="{y + 10}" x2="{x + 40}" y2="{y + 10}" stroke="#6d9fe4" stroke-width="3" stroke-dasharray="14 8"/>')
    d.t(x + 52, y + 15, label, 15)

d.save(OUT, "Banka prod topolojisi (hedef): kanal → zone → cluster → domain → veri → dış çıkış",
       "2 DC aktif-aktif · OpenShift · Istio ambient · ortak edge + ortak DMZ (kanal başına namespace, iş mantığı yok) · BFF internal'da · iç JWT'yi IdP üretir · şube kendi zone'u · ATM/POS → PCI · core legacy ayrı cluster · dışarıya yalnızca dış çıkış zone'undan",
       oy=OY)
print("ok", OUT)
