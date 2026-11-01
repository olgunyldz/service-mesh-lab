"""Topoloji diyagramı üreteci (bkz. README.md, topo_style.py)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from topo_style import Diagram

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "topology-lab.svg")
d = Diagram(1340, 1800)

# ---- Kanallar ----
d.channel(40, 110, 270, "Mobil", "mobile-api.apps.example.local")
d.channel(335, 110, 270, "Web", "www.apps.example.local")
d.channel(630, 110, 270, "Partner", "partner-api.apps.example.local")
d.channel(940, 110, 165, "Şube", "branch-api.corp.internal")
d.channel(1120, 110, 85, "ATM", "planlı", planned=True)
d.channel(1215, 110, 85, "POS", "planlı", planned=True)

# ---- Edge ----
d.zone(40, 250, 860, 100, "Edge · edge-lb (HAProxy) → edge-waf (ModSecurity CRS)",
       ["docker edge-net · TLS 1.2+ · hız sınırı · partner sertifikası · Host → kanal gateway'i"], center=True)

# ---- Sağ sütun ----
d.zone(940, 250, 165, 150, "Şube WAN", ["branch-net", "branch-terminal", "branch-fw (TCP)", "Branch CA"])
d.zone(1120, 250, 180, 150, "ATM · POS ağı", ["atm-net", "atm-fw · pos-fw", "terminal sert.", "(planlı)"], planned=True)
d.zone(940, 430, 360, 155, "Kart zone · PCI (planlı)", ["14 · pci-zone: mgmt'te izole ns", "tokenization · HSM simülasyonu", "atm/pos switch (ISO 8583) örneği"], planned=True)
d.zone(940, 790, 360, 130, "Dış hedef", ["httpbin.org (HTTP :80)", "yalnızca egress gateway'den"])
d.zone(940, 950, 360, 175, "Host'tan erişim", ["localhost:8443 → edge (kanallar, sso)", "localhost:20001 → Kiali", "localhost:3001 → Grafana", "127.0.0.1:5001 → lab-registry (push)"])

# ---- DMZ ----
d.zone(40, 395, 860, 335, "DMZ zone · kind-dmz (tek node)")
d.box(65, 450, 395, 255, "Arka uçlar ve çıkış", ["web-bff (Go) + waypoint", "auth-service (token exchange)",
      "ratelimit (Envoy) · partner kotası", "dmz-egressgw (tek kapı, port + kimlik)", "Prometheus (agent) → mgmt",
      "iç JWT imza anahtarı yalnızca burada"])
d.box(480, 450, 395, 255, "Kanal gateway'leri", ["web-gw .10 · CORS · 50 rps", "mobile-gw .11 · /mobile/v1/* · 30 rps",
      "partner-gw .12 · izin listesi · kota", "branch-gw .13 · Branch CA · XFCC", "ext_authz → auth-service (her kanal)",
      "atm-gw .14 · pos-gw .15 (planlı)"])

# ---- Internal ----
d.zone(40, 790, 860, 335, "Internal zone · kind-cluster-a")
d.box(65, 845, 395, 255, "Servisler", ["int-ingressgw .201.10 (mTLS + iç JWT)", "api-a (podinfo) + waypoint",
      "account-api (Go) + waypoint", "L7: GET/POST · rol kontrolü", "api-a önbelleği → Valkey", "imzalı image · digest'e sabit"])
d.box(480, 845, 395, 255, "Çıkış · istio-egressgw", ["443 → httpbin.org", "15432 → PostgreSQL (mgmt)", "16379 → Valkey (mgmt)",
      "80 → metrikler (Prometheus agent)", "AuthZ: port + waypoint kimliği", "uygulama mgmt adresini bilmez"])

# ---- mgmt ----
d.zone(40, 1185, 860, 335, "Paylaşılan ürünler · kind-mgmt", right="dışarıya kapalı")
d.box(65, 1240, 395, 255, "Giriş ve kimlik", ["istio-ingressgw .203.10 (ISTIO_MUTUAL)", "443 keycloak · 443 prometheus",
      "5432 postgres · 6379 valkey", "Keycloak 26.8 (optimize image)", "realm: customers · partners · staff",
      "/admin ve master realm kapalı"])
d.box(480, 1240, 395, 255, "Veri ve gözlem", ["PostgreSQL 18 (corebank, keycloak)", "Valkey 9 (ACL, önek bazlı)",
      "servis başına DB kullanıcısı", "Prometheus (merkezi, 6 saat)", "Kiali (3 cluster) · Grafana", "yedek / HA yok (lab)"])

# ---- Platform ----
d.zone(40, 1580, 1260, 195, "Platform · Docker Desktop (WSL2) üzerinde")
pl = [("Registry", ["lab-registry (imzalı)", "cache: docker · quay · ghcr"]),
      ("Politika", ["Kyverno (Deny)", "fail-closed · dar istisnalar"]),
      ("Sertifikalar", ["mesh root + 3 ara CA", "Edge · Partner · Branch CA"]),
      ("Anahtarlar", ["iç JWT anahtarı (DMZ)", "cosign anahtarı (CI)"]),
      ("Kaynak", ["apiserver GOMEMLIMIT", "Prometheus agent modu"])]
for i, (title, lines) in enumerate(pl):
    d.box(65 + i * 245, 1635, 225, 108, title, lines)

# ---- Oklar ----
for x in (175, 470, 765):
    d.arrow([(x, 188), (x, 250)])
d.arrow([(677, 350), (677, 450)])
d.arrow([(480, 590), (460, 590)])
d.t(470, 440, "ext_authz · HBONE", 14, 400, "#5f5f5a", "middle", d.l)
d.arrow([(380, 705), (380, 845)], blue=True, label="mTLS + iç JWT", lx=268, ly=770)
d.arrow([(460, 970), (480, 970)])
d.arrow([(677, 1100), (677, 1240)], blue=True, label="PostgreSQL · Valkey · metrikler", lx=690, ly=1165)
d.arrow([(65, 650), (52, 650), (52, 1300), (65, 1300)], blue=True)
d.vt(46, 980, "Keycloak · Valkey · metrikler", 14, "#1f1f1f", 600)
d.arrow([(875, 880), (940, 880)], label="HTTP", lx=885, ly=870)
# özel ağlar
d.arrow([(1022, 188), (1022, 250)])
d.arrow([(940, 330), (926, 330), (926, 640), (875, 640)])
d.vt(918, 500, "şube: TCP 443 (passthrough)")
d.arrow([(1162, 188), (1162, 250)], dashed=True)
d.arrow([(1257, 188), (1257, 250)], dashed=True)
d.arrow([(1210, 400), (1210, 430)], dashed=True)
d.arrow([(940, 545), (912, 545), (912, 690), (875, 690)], dashed=True)
d.vt(904, 620, "planlı")

d.save(OUT, "Lab topolojisi: 3 kind cluster (tek node), ambient mesh",
       "Docker Desktop · Istio 1.30 ambient · 4 aktif kanal + planlı ATM/POS · zone geçişleri yalnızca egress gateway'lerden, mTLS ile.")
print("ok", OUT)
