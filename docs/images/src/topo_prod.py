"""Topoloji diyagramı üreteci (bkz. README.md, topo_style.py)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from topo_style import Diagram

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "topology-prod.svg")
d = Diagram(1340, 2170)

# ---- Kanallar ----
d.channel(40, 110, 270, "Mobil", "m-api.banka.com.tr")
d.channel(335, 110, 270, "Web", "ib.banka.com.tr")
d.channel(630, 110, 270, "Partner", "api.banka.com.tr")
d.channel(940, 110, 165, "Şube", "SD-WAN / MPLS")
d.channel(1120, 110, 85, "ATM", "özel ağ")
d.channel(1215, 110, 85, "POS", "acquirer")

# ---- Edge ----
d.zone(40, 250, 860, 100, "Edge · GSLB → DDoS/CDN → F5 LB + WAF",
       ["f5-edge-dc1 · f5-edge-dc2 · bot koruma · TLS anahtarı HSM'de"], center=True)

# ---- Sağ sütun: özel ağlar (yan yana), kart, kimlik, dış kurumlar ----
d.zone(940, 250, 165, 150, "Şube zone", ["branch-fw", "branch-gw (A/B)", "AD SSO", "cihaz sert."])
d.zone(1120, 250, 180, 150, "ATM · POS ağı", ["atm-fw · pos-fw", "APN gateway", "terminal sert.", "ISO 8583 / NDC"])
d.zone(940, 430, 360, 180, "Kart zone · PCI DSS", ["atm-switch (NDC/DDC) · pos-switch", "iso8583-adapter · tokenization", "hsm (PIN, CVV, anahtar)", "şemalar: Visa · MC · TROY · BKM"])
d.zone(940, 790, 360, 205, "Kimlik zone", ["keycloak / RHBK (A/B)", "realm: müşteri · partner · personel", "device-registry · consent-svc", "redis-session (A/B) · AD/LDAP"])
d.zone(940, 1185, 360, 180, "Dış kurumlar", ["TCMB: EFT · FAST", "SWIFT · kart şemaları", "KKB · GİB · partner bankalar", "(yalnızca egress gateway'lerden)"])

# ---- DMZ ----
d.zone(40, 395, 860, 335, "DMZ zone")
dmz = ["web-gw · web-bff (token handler)", "mobile-gw · partner-gw (açık bankacılık)",
       "auth-service (token exchange) · consent", "ratelimit · dmz-redis (kota, jti)", "ext_authz: her kanal gateway'inde",
       "dmz-egressgw (internal'a tek kapı)"]
d.box(65, 450, 395, 255, "ocp-dmz-a · DC1", dmz)
d.box(480, 450, 395, 255, "ocp-dmz-b · DC2", dmz)

# ---- Internal ----
d.zone(40, 790, 860, 335, "Internal zone")
intz = ["int-ingressgw (mTLS + iç JWT doğrulama)", "account · transfer · customer", "card · payments · fraud",
        "notification-svc · kafka istemcileri", "waypoint: claim bazlı L7 yetki", "int-egressgw (→ core, data, kurumlar)"]
d.box(65, 845, 395, 255, "ocp-int-a · DC1", intz)
d.box(480, 845, 395, 255, "ocp-int-b · DC2", intz)

# ---- Core banking ----
d.zone(40, 1185, 860, 335, "Core banking zone")
core = ["core-ingressgw (MUTUAL TLS)", "core-api · ledger-svc", "posting-engine · limit-svc", "deposit · loan · fx",
        "eod-batch (gün sonu)", "core-egressgw (→ data, kurumlar)"]
d.box(65, 1240, 395, 255, "ocp-core-a · DC1", core)
d.box(480, 1240, 395, 255, "ocp-core-b · DC2", core)

# ---- Data ----
d.zone(40, 1580, 860, 335, "Data zone", right="A ⇄ B replikasyon")
data = ["app-pg (CloudNativePG)", "core-db (Oracle RAC / ayrı node)", "kafka (Strimzi, 3 broker)",
        "valkey-cache (ACL)", "pgBackRest · Velero → immutable yedek", "disk şifreleme · TDE"]
d.box(65, 1635, 395, 255, "ocp-data-a · DC1", data)
d.box(480, 1635, 395, 255, "ocp-data-b · DC2", data)

# ---- Yönetim ve gözlem ----
d.zone(40, 1960, 1260, 185, "Yönetim ve gözlem · ocp-mgmt-a / ocp-mgmt-b")
mg = [("Loglar", ["fluent-bit → loki/ELK", "maskeleme · saklama"]),
      ("Metrik · iz", ["prometheus · thanos", "tempo · grafana · kiali"]),
      ("SIEM / SOAR", ["korelasyon, alarm", "audit log (k8s, DB)"]),
      ("Tedarik zinciri", ["harbor · cosign · trivy", "kyverno · argocd"]),
      ("Yönetim", ["ACM · vault + HSM", "bastion · PAM (MFA)"])]
for i, (title, lines) in enumerate(mg):
    d.box(65 + i * 245, 2015, 225, 108, title, lines)

# ---- Oklar: internet kanalları ----
for x in (175, 470, 765):
    d.arrow([(x, 188), (x, 250)])
d.arrow([(262, 350), (262, 450)])
d.arrow([(677, 350), (677, 450)])
d.arrow([(262, 705), (262, 845)], blue=True, label="mTLS + iç JWT", lx=150, ly=770)
d.arrow([(677, 705), (677, 845)], blue=True)

# ---- Oklar: özel ağlar ----
d.arrow([(1022, 188), (1022, 250)])
d.arrow([(1162, 188), (1162, 250)])
d.arrow([(1257, 188), (1257, 250)])
d.arrow([(1210, 400), (1210, 430)])
# Şube -> internal (şerit x=926)
d.arrow([(940, 330), (926, 330), (926, 915), (875, 915)])
d.vt(918, 640, "şube: mTLS + iç JWT")
# Kart -> internal (şerit x=912)
d.arrow([(940, 560), (912, 560), (912, 1000), (875, 1000)])
d.vt(904, 820, "kart: mTLS · token PAN")
# DMZ (auth-service) -> Kimlik
d.arrow([(875, 640), (890, 640), (890, 760), (980, 760), (980, 790)], dashed=True)
d.t(990, 752, "auth-service → Keycloak: OIDC · JWKS", 14, 400, "#5f5f5a", layer=d.l)
# Kart -> şemalar (dış kurumlar), sağ kenardan
d.arrow([(1300, 560), (1322, 560), (1322, 1275), (1300, 1275)], dashed=True)
d.vt(1314, 1100, "kart şemaları")

# ---- Oklar: internal -> core, data; core -> kurumlar ----
d.arrow([(262, 1100), (262, 1240)], label="mTLS", lx=200, ly=1165)
d.arrow([(677, 1100), (677, 1240)])
d.arrow([(470, 1100), (470, 1580)])
d.arrow([(262, 1495), (262, 1635)], label="TLS", lx=212, ly=1560)
d.arrow([(677, 1495), (677, 1635)])
d.arrow([(875, 1300), (940, 1300)], label="EFT/FAST", lx=878, ly=1290)

d.save(OUT, "Gerçek banka ortamı (prod): 10 OpenShift cluster, 2 DC, ambient mesh",
       "Her cluster: 3 master + etcd · istiod · ztunnel (L4 mTLS) · waypoint (L7). Kanallar: mobil, web, partner (internet) · şube, ATM, POS (özel ağlar).")
print("ok", OUT)
