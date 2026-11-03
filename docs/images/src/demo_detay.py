"""Ayrıntılı demo (lab / pilot) topolojisi seti: bu makinede gerçekten çalışan ortam, genelden pod içine kadar.
Çıktı: docs/images/demo-detay/NN-*.svg (PNG için demo-detay/README.md'deki komut).
Çalıştırma: python docs/images/src/demo_detay.py [resim numaraları...]   (boş: hepsi)
Kaynak: manifests/, infra/, istio/values/, scripts/, config.env ve docs/pilot-architecture.md. Yapı prod_detay.py ile aynı."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from detay_style import D
from topo_style import PALETTE

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "demo-detay")
os.makedirs(OUT, exist_ok=True)


def out(name):
    return os.path.join(OUT, name)


def ns_pods(d, x, y, w, ns, pods, color="internal", sub=None):
    """Namespace + pod listesi (her pod tek satır: ad · tür · görev); döndürür: alt kenar"""
    h = 40 + len(pods) * 40
    d.nsbox(x, y, w, h, ns, color, sub)
    for i, (name, kind, desc) in enumerate(pods):
        agent = kind.startswith("DaemonSet")
        col = "mgmt" if agent else ("dmz" if ("waypoint" in name or "gateway" in name) else color)
        d.pod(x + 12, y + 36 + i * 40, w - 24, 34, name, kind, col, (), agent=agent)
        if desc:
            d.text(x + 12 + (w - 24) * 0.36, y + 36 + i * 40 + 19, desc, 11.5, 400, "#3a3a3a")
    return y + h


PLATFORM = [("istiod", "Deployment ×1", "xDS · mesh CA (ortak kök: corp.mesh)"),
            ("ztunnel", "DaemonSet", "L4 mTLS · HBONE :15008"),
            ("istio-cni-node", "DaemonSet", "pod trafiği → ztunnel (nftables)")]
AGENTS = [("fluent-bit", "DaemonSet", "logging-agent · pod + audit logu → mgmt Loki"),
          ("prometheus (agent modu)", "Deployment ×1", "istio-system · remote_write → mgmt")]
KUBE = [("kyverno (4 controller)", "Deployment", "admission: 6 politika · imzalı image"),
        ("metallb controller · speaker", "Deploy · DaemonSet", "LoadBalancer VIP (L2)"),
        ("kube-system", "static pod · DS", "apiserver · etcd · coredns · kindnet")]


# =====================================================================================================================
def img00():
    W, H, OY = 2200, 1370, 40
    d = D(W, H)
    d.boundary([(14, 108), (1844, 108), (1844, 1080), (14, 1080)], "BU MAKİNE · Windows 11 · Docker (WSL2) · 15,7 GB RAM · tek host", "external")
    d.boundary([(1864, 140), (2186, 140), (2186, 330), (1864, 330)], "GERÇEK İNTERNET", "public")
    d.box(1884, 170, 282, 140, "httpbin.org", ["yalnızca cluster-a egress'inden", ":80 (ServiceEntry, örnek dış", "servis çağrısı)"], color="external")
    # Docker ağları (üst)
    d.boundary([(40, 148), (1300, 148), (1300, 340), (40, 340)], "DOCKER AĞI edge-net · İNTERNET TARAFI", "public", fill_opacity=0.35)
    d.box(60, 182, 560, 140, "İstemciler (internet simülasyonu)", ["host: tarayıcı / curl → 127.0.0.1:8443", "loadgen: web girişi + dashboard · partner acme",
                                                                     "mobile-loadgen (mobile-sim): DPoP + attestation", "testler: 08-verify.sh, mobile-sim"])
    d.box(650, 182, 300, 140, "edge-lb · HAProxy 3.0", [":8443 TLS 1.2+/1.3 · HSTS", "hız ve bağlantı limiti", "partner: istemci sertifikası"], color="edge")
    d.box(980, 182, 300, 140, "edge-waf · ModSecurity", ["OWASP CRS 4.25 (engelleme)", "Host → kanal gateway VIP'i", "ağlar: edge-net + kind"], color="edge")
    d.link(1030, 168, "Ayrıntı: 01")
    d.boundary([(1330, 148), (1830, 148), (1830, 340), (1330, 340)], "DOCKER AĞI branch-net · ŞUBE WAN", "wan", fill_opacity=0.5)
    d.box(1350, 182, 220, 140, "branch-terminal", ["cihaz sertifikası", "sube-0001 · teller01", "/branch/v1/*"], color="wan")
    d.box(1590, 182, 220, 140, "branch-fw · HAProxy", ["mode tcp · yalnızca :443", "→ branch-gateway", "ağlar: branch-net + kind"], color="wan")
    # kind ağı
    d.boundary([(40, 400), (1830, 400), (1830, 970), (40, 970)], "DOCKER AĞI kind · kind node'ları + MetalLB VIP'leri (<ağ>.200–203.x)", "internal", fill_opacity=0.08)
    d.zone(60, 440, 570, 320, "kind-cluster-a · internal", [
        "1 node · istiod · ambient · waypoint'ler",
        "istio-ingressgateway VIP .201.10 :443",
        "channel-bff: web-bff · mobile-bff · branch-bff",
        "account-api: v1 (%90) · v2 (%10, canary)",
        "api-a: podinfo ×2 (genel bilgi uçları)",
        "istio-egressgateway: tek çıkış",
        "security/tx-signing: AÇIK NOKTA (yok)",
        "cluster-b: kapalı (17 · cluster-b)"], color="internal")
    d.zone(650, 440, 570, 320, "kind-dmz · iç DMZ", [
        "1 node · istiod (dmz) · iş mantığı ve veri yok",
        "gateway VIP'leri :443 (mTLS, Edge-DMZ CA):",
        "  web .200.10 · mobile .200.11",
        "  partner .200.12 · branch .200.13",
        "edge-web/web-token-handler (cookie ↔ token)",
        "auth/auth-service (ext_authz, exchange)",
        "ratelimit/ratelimit (partner kotası)",
        "istio-egress/dmz-egressgateway (tek çıkış)"], color="dmz")
    d.zone(1240, 440, 570, 320, "kind-mgmt · kimlik, veri, gözlem", [
        "1 node · istiod · ambient",
        "istio-ingressgateway VIP .203.10 (SNI ile)",
        "iam: keycloak 26.8 · device-registry",
        "data: postgres 18 · valkey 9",
        "logging: loki 3.7 · tempo 2.10",
        "istio-system: prometheus · grafana · kiali",
        "giriş yalnızca egress gateway kimlikleriyle",
        "internete kapalı"], color="mgmt")
    d.link(500, 456, "04 · 05")
    d.link(1090, 456, "02 · 03")
    d.link(1680, 456, "06 · 07")
    d.box(60, 866, 560, 86, "lab-registry:5000 (host :5001)", ["imzalı lab image'ları (cosign) · Kyverno yalnızca bunu kabul eder",
                                                                 "docker.io / quay.io / ghcr.io önbellekleri (pull-through)"], size=12)
    d.box(650, 866, 570, 86, "edge-logs · Fluent Bit (Docker)", ["edge-lb · edge-waf · branch-fw container logları",
                                                                  "→ logs-edge.mgmt.internal :443 (mTLS) → Loki"], size=12)
    d.box(1240, 866, 570, 86, "Her node'da (08)", ["ztunnel · istio-cni · fluent-bit (DaemonSet)",
                                                     "kyverno · metallb · coredns · kindnet"], size=12)
    # Host portları
    d.text(60, 1008, "Host'a açık portlar (yalnızca bu makine)", 14, 700)
    xb = 60
    for t in ["127.0.0.1:8443 → edge-lb (kanallar)", ":3001 → Grafana", ":20001 → Kiali", "127.0.0.1:8081 → Keycloak yönetimi", ":5001 → lab-registry"]:
        xb += d.badge(xb, 1042, t, "in") + 14
    # Akışlar
    d.flow([(620, 252), (650, 252)], "req")
    d.flow([(950, 252), (980, 252)], "req")
    d.flow([(1130, 322), (1130, 440)], "main", "mTLS :443 · Edge-DMZ CA", 1142, 380)
    d.flow([(1700, 322), (1700, 362), (1190, 362), (1190, 440)], "main", "cihaz sertifikası :443 → .200.13", 1260, 356)
    d.flow([(650, 720), (630, 720)], "main")
    d.flow([(1220, 720), (1240, 720)], "main")
    d.t(1225, 782, "dmz-egressgateway → cluster-a .201.10:443 (mTLS + iç JWT) · → mgmt .203.10 (SSO, cihaz, Valkey)", 12.5, 600, "#1f1f1f", "middle", d.l)
    d.flow([(400, 760), (400, 812), (1500, 812), (1500, 760)], "main")
    d.t(410, 834, "cluster-a istio-egressgateway → mgmt: postgres :15432→5432 · valkey · cihaz kaydı (mTLS)", 12.5, 600, "#1f1f1f", "start", d.l)
    d.flow([(200, 760), (200, 846), (1838, 846), (1838, 250), (1884, 250)], "req")
    d.t(1826, 840, "cluster-a egress → httpbin.org :80", 12, 400, "#5f5f5a", "end", d.l)
    d.flow([(300, 322), (300, 440)], "deny", "istemci → cluster: yol yok", 312, 424)
    d.note(40, 1100, 860, "Okuma sırası · siyah etiket = ayrıntı resmi", [
        "00 · genel bakış (bu resim)", "01 · Docker ağları: istemciler, edge, şube, registry, edge-logs",
        "02 · kind-dmz: namespace'ler, pod'lar · 03 · DMZ pod içi: gateway filtreleri, auth-service",
        "04 · kind-cluster-a: namespace'ler, pod'lar · 05 · account-api pod'u, waypoint kuralları (canary)",
        "06 · kind-mgmt: kimlik, veri, SNI giriş tablosu · 07 · gözlem hattı: log, metrik, iz",
        "08 · bir kind node'unun anatomisi · 09 · uçtan uca: mobil transfer, adım adım"], 12.5)
    d.legend(920, 1100, 1266, [("public", "internet tarafı"), ("wan", "şube ağı"), ("edge", "edge"), ("dmz", "DMZ"), ("internal", "internal"),
                               ("mgmt", "yönetim / kimlik / veri"), ("external", "host / dış")], extra=True, cols=4)
    d.save(out("00-genel-bakis.svg"), "00 · Genel bakış: bu makinedeki demo ortamı (kind, Docker ağları, 3 cluster)",
           "hedef mimarinin küçültülmüş hali · her blok siyah etiketteki resimde açılır · mavi = mTLS ana akış · kırmızı kesikli = yasak yol", oy=OY)


# =====================================================================================================================
def img01():
    W, H, OY = 2200, 1030, 40
    d = D(W, H)
    d.boundary([(20, 160), (1180, 160), (1180, 548), (20, 548)], "DOCKER AĞI edge-net · İNTERNET TARAFI · cluster'lara erişemez", "public", fill_opacity=0.3)
    d.badge(560, 126, "in ← host: 127.0.0.1:8443 (HTTPS) · :8080 (→ HTTPS'e yönlendirme)", "in")
    eb = d.pod(40, 196, 560, None, "edge-lb", "Docker container · edge-net", "edge", [
        ("haproxy:3.0-alpine", "proxy", [":8443 TLS 1.2+/1.3 · h2 · HSTS · modern cipher'lar", "IP başına hız (100 / 10 sn) ve bağlantı limiti",
                                         "dışarıdan gelen X-Forwarded-*, x-user-jwt, x-channel silinir", "partner-api: Partner CA istemci sertifikası zorunlu",
                                         "  sertifika CN'i → x-partner-id", "→ edge-waf:8080"])])
    wb = d.pod(620, 196, 540, None, "edge-waf", "Docker container · edge-net + kind", "edge", [
        ("modsecurity-crs:4.25 (nginx)", "proxy", ["ModSecurity v3 + OWASP CRS (paranoia 1, mod On)", "403'lerde tek tip gövde",
                                                   "Host → kanal gateway VIP'i (.200.10 – .12) :443", "DMZ'ye istemci sertifikası: Edge-DMZ CA",
                                                   "kind ağına bağlı tek internet tarafı container'ı", ""])])
    lb = d.pod(40, eb + 20, 360, None, "loadgen", "Docker · edge-net", "public", [
        ("curl:8.11.1", "app", ["5 sn'de bir: web girişi (PKCE)", "dashboard · echo (CSRF)", "partner acme: client credentials", "  + istemci sertifikası", "10 istekte bir /api/status/500"])])
    d.pod(420, eb + 20, 360, None, "mobile-loadgen", "Docker · edge-net", "public", [
        ("mobile-sim:0.1.1", "app", ["mobil uygulama (kullanıcı mehmet)", "PKCE + OTP (seviye 2)", "cihaz anahtarı kaydı", "her istek: DPoP + attestation", "5 sn'de bir hesap sorgusu"])])
    d.pod(800, eb + 20, 360, None, "mobile-sim (test)", "docker run --rm", "public", [
        ("mobile-sim:0.1.1", "app", ["08-verify.sh'in mobil istemcisi", "kullanıcı ayse", "çalınan anahtar, tekrar,", "root'lu cihaz, eski sürüm", "senaryoları"])])
    # şube
    d.boundary([(1210, 160), (2180, 160), (2180, 548), (1210, 548)], "DOCKER AĞI branch-net · ŞUBE WAN · internetten ayrı", "wan", fill_opacity=0.45)
    tb = d.pod(1230, 196, 450, None, "branch-terminal", "Docker · branch-net", "wan", [
        ("curl", "app", ["cihaz sertifikası (Branch CA): sube-0001", "ikinci şube: sube-0002 (testlerde)", "personel token'ı: staff realm, teller01",
                         "  (/sso/realms/staff/* üzerinden)", "5 sn'de bir /branch/v1/accounts"])])
    fb = d.pod(1700, 196, 460, None, "branch-fw", "Docker · branch-net + kind", "wan", [
        ("haproxy:3.0-alpine", "proxy", ["iç firewall'u temsil eder", "mode tcp · yalnızca :443", "→ branch-gateway VIP .200.13:443",
                                         "şube ağından başka hedefe yol yok", "TLS'e dokunmaz (uçtan uca mTLS)"])])
    d.note(1230, tb + 22, 690, "Şube kanalı neden ayrı ağda?", ["Hedefte şube kurum WAN'ından (MPLS) gelir; edge'den geçmez.",
                                                                 "Lab'de branch-net ayrı Docker ağı: tek çıkışı branch-fw.",
                                                                 "branch-gateway DMZ cluster'ında · bkz. 02."], 12.5)
    # kind ağı
    d.boundary([(20, 610), (2180, 610), (2180, 790), (20, 790)], "DOCKER AĞI kind · node'lar, VIP'ler, registry", "internal", fill_opacity=0.1)
    for i, (n, vip, lnk) in enumerate([("cluster-a-control-plane", "VIP .201.10 (istio-ingressgateway)", "04"),
                                       ("mgmt-control-plane", "VIP .203.10 · NodePort 30201/30300/30808", "06"),
                                       ("dmz-control-plane", "VIP .200.10–.13 (4 kanal gateway'i)", "02")]):
        x = 40 + i * 400
        d.node(x, 640, 380, 120, n, None)
        d.text(x + 12, 690, "kindest/node v1.36 · containerd · tek node", 12)
        d.text(x + 12, 712, vip, 12, 600)
        d.text(x + 12, 734, "ayrıntı: " + lnk + " · node içi: 08", 12, 400, "#5f5f5a")
    d.pod(1250, 640, 450, None, "lab-registry", "Docker · kind · host :5001", "mgmt", [
        ("registry:2.8.3", "data", ["lab-registry:5000 · imzalı lab image'ları (cosign)", "+ docker.io / quay.io / ghcr.io önbellekleri"])])
    d.pod(1720, 640, 440, None, "edge-logs", "Docker · kind", "mgmt", [
        ("fluent-bit", "agent", ["/var/lib/docker/containers (salt okunur)", "log.category etiketli container'lar",
                                 "→ logs-edge.mgmt.internal :443 mTLS"])])
    # akışlar
    d.flow([(560, 136), (560, 160), (320, 160), (320, 196)], "main")
    d.flow([(600, 300), (620, 300)], "req")
    d.flow([(220, eb + 20), (220, eb)], "req")
    d.flow([(600, eb + 60), (600, eb + 6)], "req")
    d.flow([(1100, wb), (1100, wb + 8), (1170, wb + 8), (1170, 640)], "main", "kanal gateway VIP'leri :443 (mTLS) →", 1158, 584, "end")
    d.flow([(1930, fb), (1930, 590), (1190, 590), (1190, 640)], "main", "→ .200.13:443 (cihaz mTLS)", 1400, 584)
    d.flow([(220, lb), (220, 640)], "deny", "edge-net → kind: yol yok (köprü yalnızca edge-waf)", 232, 584)
    d.legend(20, 820, 2160, [("public", "internet tarafı"), ("edge", "edge"), ("wan", "şube ağı"), ("internal", "kind ağı"), ("mgmt", "registry / log")],
             extra=True, cols=6)
    d.save(out("01-docker-aglari-edge-sube.svg"), "01 · Docker ağları: istemciler, edge (LB + WAF), şube ağı, registry",
           "Kubernetes dışındaki her şey Docker container'ı · üç ayrı ağ · cluster'lara yalnızca edge-waf ve branch-fw köprü kurar", oy=OY)


# =====================================================================================================================
def img02():
    W, H, OY = 2200, 1110, 40
    d = D(W, H)
    d.badge(40, 128, "in ← edge-waf: .200.10 www/sso · .200.11 mobile · .200.12 partner (:443 mTLS) · branch-fw: .200.13", "in")
    d.badge(2160, 128, "out → cluster-a .201.10:443 · mgmt .203.10 (SSO, cihaz, Valkey, log / metrik / iz)", "out", anchor="end")
    c = [40, 760, 1480]
    cw = 680
    y = 170
    y = ns_pods(d, c[0], y, cw, "istio-ingress", [("dmz-ingressgateway", "Deployment ×1", "LB .200.10 · www + sso · CORS · 50 rps")], "dmz") + 14
    y = ns_pods(d, c[0], y, cw, "istio-mobile", [("mobile-gateway", "Deployment ×1", "LB .200.11 · /mobile/v1 · 30 rps · ext_authz")], "dmz") + 14
    y = ns_pods(d, c[0], y, cw, "istio-partner", [("partner-gateway", "Deployment ×1", "LB .200.12 · izin listesi · 5 rps + global kota")], "dmz") + 14
    y = ns_pods(d, c[0], y, cw, "istio-branch", [("branch-gateway", "Deployment ×1", "LB .200.13 · cihaz sertifikası (XFCC)")], "dmz") + 14
    b1 = ns_pods(d, c[0], y, cw, "istio-egress", [("dmz-egressgateway", "Deployment ×1", "TEK çıkış · ClusterIP · kaynak AuthZ")], "dmz")
    y = 170
    y = ns_pods(d, c[1], y, cw, "edge-web", [("web-token-handler", "Deployment ×1", "cookie ↔ token · CSRF · oturum: Valkey"),
                                             ("waypoint", "Deployment ×1", "L7: yalnızca dmz-ingressgateway")], "dmz", "ambient · waypoint") + 14
    y = ns_pods(d, c[1], y, cw, "auth", [("auth-service", "Deployment ×1", "ext_authz · introspection · exchange"),
                                         ("waypoint", "Deployment ×1", "L7: token handler + 3 gateway")], "dmz", "ambient · waypoint") + 14
    b2 = ns_pods(d, c[1], y, cw, "ratelimit", [("ratelimit", "Deployment ×1", "Envoy ratelimit · :8081 gRPC · sayaç Valkey'de"),
                                               ("waypoint", "Deployment ×1", "L7: yalnızca partner-gateway")], "dmz", "ambient · waypoint")
    y = 170
    y = ns_pods(d, c[2], y, cw, "istio-system", PLATFORM + [AGENTS[1]], "mgmt") + 14
    y = ns_pods(d, c[2], y, cw, "logging-agent", [AGENTS[0]], "mgmt", "PSA: privileged (hostPath /var/log)") + 14
    b3 = ns_pods(d, c[2], y, cw, "kyverno · metallb-system · kube-system", KUBE, "mgmt")
    d.text(c[1] + 12, b2 + 30, "Egress gateway'e kim, nereye çıkabilir (AuthorizationPolicy):", 13, 700)
    rows = ["edge-web waypoint · mobile/partner/branch gateway → cluster-a (BFF'ler) :443",
            "dmz-ingressgateway → sso (yalnızca /realms/customers|partners/*, /resources/*)",
            "auth · edge-web · ratelimit waypoint'leri → mgmt Valkey :16379",
            "auth waypoint → devices.mgmt.internal (yalnızca GET /v1/devices/lookup)",
            "herkes (yalnızca POST) → log, metrik, iz push uçları :80"]
    for i, r in enumerate(rows):
        d.text(c[1] + 12, b2 + 54 + i * 20, "· " + r, 12)
    # akışlar
    d.flow([(380, 112), (380, 206)], "main")
    bot = max(b1, b2 + 160, b3) + 30
    d.boundary([(14, 96), (2186, 96), (2186, bot), (14, bot)], "kind-dmz · tek node (dmz-control-plane) · iş mantığı ve veri yok", "dmz", fill_opacity=0.15)
    d.flow([(720, 223), (772, 223)], "req")
    d.flow([(720, 317), (746, 317), (746, 357), (772, 357)], "aux")
    d.t(724, 342, "ext_authz", 11.5, 400, "#5f5f5a", "start", d.l)
    d.flow([(380, b1), (380, bot + 30)], "main", "dmz-egressgateway → cluster-a :443 · mgmt :443 / :6379 (mTLS)", 392, bot + 24)
    d.flow([(1500, bot - 60), (1500, bot + 30)], "deny", "DMZ → PostgreSQL, cluster-a pod'ları (doğrudan): yol yok", 1512, bot + 24)
    d.note(40, bot + 50, 1080, "Bu resimde", ["Kanal gateway'leri ayrı namespace ve ayrı VIP: biri düşse ya da açık verse diğerleri etkilenmez.",
                                          "Uygulama namespace'leri ambient: sidecar yok, mTLS ztunnel'de, L7 kurallar namespace'in waypoint'inde.",
                                          "Internal'a ve mgmt'e tek kapı dmz-egressgateway; dış token DMZ'de kalır, içeri iç JWT gider.",
                                          "Pod içi (filtre zinciri, container, port): 03."], 12.5)
    d.legend(1140, bot + 50, 1040, [("dmz", "gateway / waypoint / DMZ"), ("mgmt", "platform")], extra=True, cols=3)
    d.save(out("02-dmz-cluster.svg"), "02 · kind-dmz cluster'ı: namespace'ler, pod'lar, egress kuralları",
           "her kutu bir namespace · satırlar pod'lar (ad · iş yükü · replika · görev) · gateway ve waypoint'ler turuncu kenarlı", oy=OY)


# =====================================================================================================================
def img03():
    W, H, OY = 2200, 1150, 40
    d = D(W, H)
    d.boundary([(14, 96), (2186, 96), (2186, 850), (14, 850)], "kind-dmz · dmz-control-plane node'unun içi (tek node)", "dmz", fill_opacity=0.15)
    d.node(40, 130, 2120, 700, "dmz-control-plane (kindest/node · containerd · kubelet)", "lab'de tek node: gateway'ler ve uygulama pod'ları aynı node'da")
    d.nsbox(60, 172, 1010, 400, "istio-mobile", "dmz")
    gb = d.pod(80, 210, 970, None, "mobile-gateway-…", "Deployment ×1 · SA mobile-gateway", "dmz", [
        ("istio-proxy (Envoy) · gateway modu: Envoy pod'un kendisi", "proxy", [
            "listener :443 · TLS (mobile-api sertifikası) · istemci sertifikası yalnızca Edge-DMZ CA (edge-waf)",
            "filtre 1 · header temizliği: x-user-jwt, x-partner-id silinir · x-channel=mobile yazılır",
            "filtre 2 · local rate limit: 30 rps",
            "filtre 3 · ext_authz → auth-service.auth:8080 (DPoP, attestation, introspection, exchange) · ret: 401 / 403 / 426",
            "route · /mobile/v1/* → önek kaldırılır → dmz-egressgateway:443 · Host mobile-bff.apps.example.local · x-user-jwt",
            "erişim logu (JSON: request_id, channel, trace_id, upstream_attempts) → stdout · iz → OTLP (%10)",
            "yönetim: :15021 sağlık · :15090 metrik · :15000 admin (yalnızca pod içi)"]),
        ("pilot-agent", "agent", ["xDS → istiod (dmz) :15012 (mTLS) · SPIFFE: corp.mesh/ns/istio-mobile/sa/mobile-gateway"])])
    d.badge(80, gb + 24, "in :443 ← edge-waf (yalnızca Edge-DMZ CA)", "in")
    d.badge(1050, gb + 24, "out → auth-service :8080 (HBONE) · dmz-egressgateway :443", "out", anchor="end")
    ay = gb + 62
    d.text(60, ay, "Node agent'ları (DaemonSet · her node'da bir tane)", 14, 700)
    ag = [("ztunnel", ["istio-system · L4 mTLS", "in :15008 HBONE", "çıkış yakalama :15001", "DNS proxy :15053"]),
          ("istio-cni-node", ["pod ağına nftables", "kuralı yazar: pod", "trafiği → ztunnel", "(pod'a yetki gerekmez)"]),
          ("fluent-bit", ["/var/log/pods + audit", "Lua: kategori, maskeleme", "kategori → Loki tenant'ı", "→ egress :80 → mgmt"]),
          ("kube-proxy · kindnet", ["Service → pod (iptables)", "pod ağı (CNI)", "", ""])]
    for k, (n, ls) in enumerate(ag):
        d.pod(60 + k * 254, ay + 14, 244, None, n, "DaemonSet", "mgmt", [(n, "agent", [l for l in ls if l])], agent=True)
    d.nsbox(1110, 172, 1030, 330, "auth", "dmz", "istio.io/use-waypoint: waypoint")
    wb = d.pod(1130, 210, 470, None, "waypoint-…", "Deployment ×1", "dmz", [
        ("istio-proxy (Envoy) · L7", "proxy", ["in :15008 HBONE (yalnızca mesh kimlikleri)", "AuthZ: kaynak = token handler + 3 gateway",
                                                 "erişim logu · iz span'i (OTLP)"])])
    d.pod(1620, 210, 500, None, "auth-service-…", "Deployment ×1 · SA auth-service", "dmz", [
        ("auth-service (Go, distroless, non-root)", "app", [":8080 ext_authz kontrol ucu", "salt okunur kök dosya sistemi · yetenek yok",
                                                           "iç JWT önbelleği (30 sn)"]),
        ("secret (Kubernetes Secret)", "data", ["exchange client secret'ları", "attestation açık anahtarı"]),
        ("kimlik", "init", ["SPIFFE: corp.mesh/ns/auth/sa/auth-service", "sertifikayı ztunnel tutar"])])
    for k, (t, kind) in enumerate([("in ← token handler · 3 gateway (HBONE :15008)", "in"), ("out → Keycloak (egress → mgmt :443)", "out"),
                                   ("out → Valkey dpop: (egress :16379)", "out"), ("out → device-registry lookup (egress)", "out")]):
        d.badge(1130, wb + 22 + k * 26, t, kind)
    d.nsbox(1110, 518, 1030, 150, "edge-web", "dmz", "ambient · waypoint")
    d.pod(1130, 556, 470, None, "web-token-handler-…", "Deployment ×1", "dmz", [
        ("handler (Go)", "app", [":8080 · __Host-sid ↔ oturum (Valkey sess:)", "CSRF · refresh rotation · izinli header'lar"])])
    d.pod(1620, 556, 500, None, "waypoint-…", "Deployment ×1", "dmz", [
        ("istio-proxy (Envoy) · L7", "proxy", ["yalnızca dmz-ingressgateway → :8080", "çıkış: web-bff, Keycloak, Valkey (egress)"])])
    d.note(60, ay + 165, 1010, "İstek yolu (numaralar)", [
        "1  edge-waf → mobile-gateway :443 (mTLS)    2  mobile-gateway → HBONE :15008 → auth waypoint",
        "3  waypoint: kaynak kimliği izinli mi?    4  waypoint → auth-service :8080 (ztunnel üzerinden)",
        "5  auth-service → Valkey (jti) · device-registry · Keycloak (introspection + exchange) → iç JWT",
        "6  karar + iç JWT mobile-gateway'e döner    7  mobile-gateway → dmz-egressgateway :443 → cluster-a (04)"], 12.5)
    d.flow([(560, 98), (560, 210)], "main")
    d.marker(576, 150, 1, "#1d7a46")
    d.flow([(1050, 300), (1090, 300), (1090, 260), (1130, 260)], "main")
    d.marker(1090, 282, 2, "#2f7bd8")
    d.marker(1365, 202, 3, "#2f7bd8")
    d.flow([(1600, 280), (1620, 280)], "main")
    d.marker(1610, 262, 4, "#2f7bd8")
    d.marker(1590, wb + 74, 5, "#c2410c")
    d.flow([(1130, 330), (1070, 330), (1070, 360), (1050, 360)], "req")
    d.marker(1070, 380, 6, "#1f1f1f")
    d.flow([(80, 460), (30, 460), (30, 880)], "main", "→ dmz-egressgateway :443 → cluster-a (04)", 42, 874)
    d.marker(30, 620, 7, "#2f7bd8")
    d.legend(40, 900, 2140, [("dmz", "DMZ"), ("mgmt", "platform / node agent")], extra=True, cols=6)
    d.save(out("03-dmz-pod-detay.svg"), "03 · DMZ pod içi: mobile-gateway (Envoy filtre zinciri), auth-service, token handler, waypoint",
           "pod → container → port ve görev · numaralar: mobil isteğin DMZ içindeki yolu · ambient: uygulama pod'larında sidecar yok", oy=OY)


# =====================================================================================================================
def img04():
    W, H, OY = 2200, 1080, 40
    d = D(W, H)
    d.badge(40, 128, "in ← dmz-egressgateway → VIP .201.10:443 (ISTIO_MUTUAL + Keycloak imzalı iç JWT)", "in")
    d.badge(2160, 128, "out → mgmt .203.10 (postgres, valkey, cihaz, log / metrik / iz) · httpbin.org :80", "out", anchor="end")
    c = [40, 760, 1480]
    cw = 680
    y = ns_pods(d, c[0], 170, cw, "istio-ingress", [("istio-ingressgateway", "Deployment ×1", "LB .201.10 · web/mobile/branch-bff, api-a"),
                                                   ("RequestAuthentication", "", "iç JWT: 3 realm · aud internal-apis"),
                                                   ("AuthorizationPolicy", "", "yalnızca dmz-egressgateway kimliği")]) + 14
    y = ns_pods(d, c[0], y, cw, "istio-egress", [("istio-egressgateway", "Deployment ×1", "TEK çıkış · kaynak waypoint'e göre AuthZ"),
                                                 ("ServiceEntry", "", "postgres · valkey · devices · httpbin")]) + 14
    b1 = ns_pods(d, c[0], y, cw, "security (yok)", [("tx-signing", "AÇIK NOKTA", "09d atlandı: işlem imzası doğrulanmıyor")])
    y = ns_pods(d, c[1], 170, cw, "channel-bff", [("web-bff", "Deployment ×1", "dashboard · seviye ipucu · → api-a, account-api"),
                                                 ("mobile-bff", "Deployment ×1", "mobil · cihaz kaydı · seviye 2 kontrolü"),
                                                 ("branch-bff", "Deployment ×1", "şube · mesai saati · dört göz"),
                                                 ("waypoint", "Deployment ×1", "L7: BFF başına issuer + channel claim")], sub="ambient · waypoint") + 14
    y = ns_pods(d, c[1], y, cw, "account-api", [("account-api (v1)", "Deployment ×1", "hesap · transfer · BOLA · %90"),
                                                ("account-api-v2", "Deployment ×1", "canary · aynı image, RELEASE=v2 · %10"),
                                                ("waypoint", "Deployment ×1", "JWT · AuthZ · VS/DR (retry, timeout)")], sub="ambient · waypoint (05)") + 14
    b2 = ns_pods(d, c[1], y, cw, "api-a", [("api-a", "Deployment ×2", "podinfo · genel bilgi uçları · scope"),
                                           ("waypoint", "Deployment ×1", "GET retry · outlier detection")], sub="ambient · waypoint")
    y = ns_pods(d, c[2], 170, cw, "istio-system", PLATFORM + [AGENTS[1]], "mgmt") + 14
    y = ns_pods(d, c[2], y, cw, "logging-agent", [AGENTS[0]], "mgmt") + 14
    b3 = ns_pods(d, c[2], y, cw, "kyverno · metallb-system · kube-system", KUBE, "mgmt")
    d.text(c[0] + 12, b1 + 30, "Egress gateway: kim → nereye", 13, 700)
    for i, r in enumerate(["account-api waypoint → :15432 → postgres.mgmt.internal:5432",
                           "api-a waypoint → :16379 → valkey · → httpbin.org",
                           "channel-bff waypoint → devices.mgmt.internal :443",
                           "herkes (yalnızca POST) → log / metrik / iz :80"]):
        d.text(c[0] + 12, b1 + 52 + i * 20, "· " + r, 12)
    d.flow([(380, 112), (380, 206)], "main")
    d.flow([(720, 226), (772, 226)], "main", "→ BFF", 724, 216)
    d.text(c[1] + 12, b2 + 22, "BFF → domain servisi: hedef namespace'in waypoint'i üzerinden (HBONE mTLS, iç JWT taşınır)", 12.5, 600, "#1f1f1f")
    bot = max(b1 + 130, b2 + 40, b3) + 30
    d.boundary([(14, 96), (2186, 96), (2186, bot), (14, bot)], "kind-cluster-a · internal · tek node (cluster-a-control-plane)", "internal", fill_opacity=0.12)
    d.flow([(52, 397), (24, 397), (24, bot + 30)], "main", "istio-egressgateway → mgmt (mTLS) · httpbin.org", 36, bot + 24)
    d.flow([(1560, bot - 60), (1560, bot + 30)], "deny", "pod → dış dünya / mgmt (doğrudan): yol yok", 1572, bot + 24)
    d.note(40, bot + 50, 1080, "Bu resimde", ["Her servis kendi namespace'inde; her namespace'in waypoint'i L7 yetkiyi uygular (issuer, kanal, scope).",
                                          "Domain servisleri kanalı yalnızca kendi BFF'inin kimliğinden kabul eder (web-bff, mobile-bff, branch-bff).",
                                          "Dışarı yalnızca istio-egressgateway'den; hedefler ServiceEntry ile tanımlı.",
                                          "account-api pod'unun içi ve trafik kuralları: 05 · node: 08."], 12.5)
    d.legend(1140, bot + 50, 1040, [("internal", "internal"), ("dmz", "gateway / waypoint"), ("mgmt", "platform")], extra=True, cols=3)
    d.save(out("04-internal-cluster.svg"), "04 · kind-cluster-a: BFF'ler, domain servisleri, waypoint'ler, giriş ve çıkış",
           "her kutu bir namespace · satırlar pod'lar (ad · iş yükü · replika · görev) · gateway ve waypoint'ler turuncu kenarlı", oy=OY)


# =====================================================================================================================
def img05():
    W, H, OY = 2200, 1130, 40
    d = D(W, H)
    d.boundary([(14, 96), (2186, 96), (2186, 850), (14, 850)], "kind-cluster-a · account-api namespace'i (12 · traffic-mgmt)", "internal", fill_opacity=0.12)
    d.node(40, 130, 1460, 700, "cluster-a-control-plane (kindest/node · containerd)", "tek node")
    d.nsbox(60, 172, 1420, 488, "account-api", "internal", "istio.io/use-waypoint: waypoint · PSA restricted")
    wb = d.pod(80, 210, 600, None, "waypoint-…", "Deployment ×1 · L7", "dmz", [
        ("istio-proxy (Envoy)", "proxy", [
            "in :15008 HBONE · yalnızca mesh kimlikleri",
            "RequestAuthentication: iç JWT (customers / partners /",
            "  staff realm'i, aud internal-apis, Keycloak JWKS)",
            "AuthZ: web-bff, mobile-bff, branch-bff, ingress (partner)",
            "VirtualService read (GET): v1 %90 · v2 %10",
            "  timeout 3 sn · 2 yeniden deneme (1 sn / deneme)",
            "VirtualService write (POST): timeout 5 sn · retry YOK",
            "DestinationRule: en çok 50 bağlantı · 20 bekleyen",
            "  outlier: 5 ardışık 5xx → 15 sn havuz dışı",
            "erişim logu (upstream_attempts) · metrik (proxyStatsMatcher)"])])
    d.badge(80, wb + 22, "in ← channel-bff BFF'leri · istio-ingressgateway (HBONE)", "in")
    v1 = d.pod(720, 210, 740, None, "account-api-…  (version: v1)", "Deployment ×1 · SA account-api", "internal", [
        ("api (Go, distroless, non-root 65532)", "app", [":8080 HTTP · /accounts · /accounts/{id}/transfers · onaylar",
                                                       "RELEASE=v1 · BOLA (sahiplik) · seviye 2 (son 5 dk) · onay limiti 10.000",
                                                       "personel: yalnızca kendi şubesi · dört göz (CHECK)"]),
        ("secret · env", "data", ["PGHOST postgres.account-api (seçicisiz Service → egress)", "DB parolası: Kubernetes Secret (05b), servis başına rol"]),
        ("kimlik", "init", ["SPIFFE: corp.mesh/ns/account-api/sa/account-api · sertifika ztunnel'de"])])
    v2 = d.pod(720, v1 + 14, 740, None, "account-api-v2-…  (version: v2)", "Deployment ×1 · canary", "internal", [
        ("api (aynı imzalı image, RELEASE=v2)", "app", ["yanıtta release=v2 · yalnızca waypoint ağırlığıyla trafik alır (%10)"])])
    for k, (t, kind) in enumerate([("in ← waypoint (HBONE :15008 → :8080)", "in"),
                                   ("out → postgres.account-api:5432 → waypoint → egress :15432 → mgmt", "out"),
                                   ("out → log (stdout → fluent-bit) · iz (traceparent taşınır)", "out")]):
        d.badge(720, v2 + 26 + k * 26, t, kind)
    d.pod(60, 676, 1420, 34, "ztunnel (DaemonSet): bu node'daki tüm pod'ların mTLS'i ve L4 yetkisi · istio-cni · fluent-bit", "DaemonSet", "mgmt", [], agent=True)
    d.note(60, 724, 1420, "İstek yolu (numaralar)", [
        "1 mobile-bff → (ztunnel → HBONE) → account-api waypoint    2 waypoint: JWT, AuthZ, rota (GET: v1/v2 ağırlıklı, retry · POST: retry yok) → pod :8080",
        "3 account-api → postgres (waypoint → istio-egressgateway :15432 → mgmt :5432, mTLS)"], 12.5)
    d.zone(1520, 130, 650, 700, "Pod'un güvenlik ve işletim ayarları", color="note")
    cards = [("İmaj", ["lab-registry:5000 · cosign imzalı · digest", "Kyverno: imzasız / latest / başka registry ret"]),
             ("Çalışma", ["runAsNonRoot (65532) · readOnlyRootFilesystem", "seccomp RuntimeDefault · yetenek: hiçbiri"]),
             ("Kaynak", ["requests: 10m CPU · 16 Mi bellek", "lab: tek replika (v1 + v2)"]),
             ("Kimlik", ["servis hesabı → SPIFFE (mesh)", "AuthZ: pod'a yalnızca kendi waypoint'i"]),
             ("Ağ", ["dışarı yalnızca egress (ServiceEntry)", "postgres: seçicisiz Service + VirtualService"]),
             ("Gözlem", ["stdout JSON log → Loki (apps)", "waypoint: istek sayısı, deneme, ejection"]),
             ("Canary geçişi", ["ağırlık: 18-traffic-policies.yaml", "geri dönüş: v2 ağırlığı 0, kod değişmez"])]
    cy = 186
    for t, ls in cards:
        d.box(1540, cy, 610, 80, t, ls, color="internal", size=12)
        cy += 88
    d.marker(576, 150, 1, "#2f7bd8")
    d.flow([(560, 98), (560, 210)], "main")
    d.flow([(680, 300), (720, 300)], "main")
    d.marker(700, 282, 2, "#2f7bd8")
    d.marker(706, v2 + 52, 3, "#c2410c")
    d.flow([(1480, v2 + 52), (1505, v2 + 52), (1505, 880)], "main", "→ istio-egressgateway → mgmt postgres (06)", 1494, 876, "end")
    d.legend(40, 900, 2140, [("internal", "internal"), ("dmz", "waypoint (Envoy)"), ("mgmt", "platform"), ("note", "ayarlar")], extra=True, cols=6)
    d.save(out("05-internal-pod-detay.svg"), "05 · Internal pod içi: account-api (v1 + v2 canary), waypoint'in L7 ve trafik kuralları",
           "pod → container → port · kimlik ve secret · waypoint: JWT, AuthZ, canary, timeout, retry, outlier · numaralar: transfer isteğinin yolu", oy=OY)


# =====================================================================================================================
def img06():
    W, H, OY = 2200, 1100, 40
    d = D(W, H)
    d.badge(40, 128, "in ← dmz-egressgateway · istio-egressgateway → VIP .203.10 (SNI) · edge-logs (mTLS)", "in")
    d.badge(2160, 128, "in ← host: :3001 Grafana · :20001 Kiali · 127.0.0.1:8081 Keycloak yönetimi", "in", anchor="end")
    c = [40, 760, 1480]
    cw = 680
    y = ns_pods(d, c[0], 170, cw, "istio-ingress", [("istio-ingressgateway", "Deployment ×1", "LB .203.10 · SNI'ye göre (tablo) · NodePort 30808")], "mgmt") + 14
    # SNI tablosu
    d.text(c[0] + 12, y + 8, "Giriş tablosu: SNI / port → hedef (kim gelebilir)", 13, 700)
    rows = [("keycloak.mgmt.internal :443", "iam/keycloak /realms/", "dmz-egress"),
            ("devices.mgmt.internal :443", "iam/device-registry", "dmz (lookup) · cluster-a"),
            ("postgres.mgmt.internal :5432", "data/postgres", "istio-egress (cluster-a)"),
            ("valkey.mgmt.internal :6379", "data/valkey", "iki egress"),
            ("prometheus.mgmt.internal :443", "prometheus /api/v1/write", "iki egress"),
            ("logs.mgmt.internal :443", "loki push", "egress'ler"),
            ("logs-edge.mgmt.internal :443", "loki push (MUTUAL)", "edge-logs"),
            ("traces.mgmt.internal :443", "tempo /v1/traces", "egress'ler"),
            (":8081 HTTP (NodePort)", "keycloak yönetim konsolu", "yalnızca localhost")]
    for i, (a, b, cc) in enumerate(rows):
        ry = y + 20 + i * 26
        d.n.append(f'<rect x="{c[0]}" y="{ry}" width="{cw}" height="23" rx="3" fill="{"#f1f8f1" if i % 2 else "#ffffff"}" stroke="#c4c4bf" stroke-width="0.8"/>')
        d.text(c[0] + 8, ry + 16, a, 12, 700)
        d.text(c[0] + 262, ry + 16, b, 12)
        d.text(c[0] + 470, ry + 16, cc, 12, 400, "#5f5f5a")
    y = y + 20 + len(rows) * 26 + 20
    b1 = ns_pods(d, c[0], y, cw, "istio-egress", [("istio-egressgateway", "Deployment ×1", "mgmt'in kendi iz çıkışı (→ tempo)")], "mgmt")
    y = ns_pods(d, c[1], 170, cw, "iam", [("keycloak", "Deployment ×1", "26.8 optimize · customers / partners / staff"),
                                          ("device-registry", "Deployment ×1", "mobil cihaz anahtarları (PostgreSQL)")], "identity", "ambient") + 14
    y = ns_pods(d, c[1], y, cw, "data", [("postgres", "StatefulSet ×1", "18 · corebank · servis başına rol"),
                                         ("valkey", "Deployment ×1", "9 · önek bazlı ACL kullanıcıları")], "data", "ambient") + 14
    d.text(c[1] + 12, y + 8, "Valkey kullanıcıları (önek → sahibi)", 13, 700)
    for i, r in enumerate(["web_session → sess:* (token handler oturumları)", "dpop → dpop:* (auth-service, DPoP jti tekrarı)",
                           "ratelimit → rl:* (partner kotası sayaçları)", "default kullanıcı kapalı · çapraz önek NOPERM"]):
        d.text(c[1] + 12, y + 30 + i * 20, "· " + r, 12)
    y += 30 + 4 * 20 + 20
    b2 = ns_pods(d, c[1], y, cw, "logging", [("loki", "StatefulSet ×1", "3.7 · kategori başına tenant · 24 saat"),
                                             ("tempo", "StatefulSet ×1", "2.10 · OTLP :4318 · izler")], "mgmt")
    y = ns_pods(d, c[2], 170, cw, "istio-system", [("istiod", "Deployment ×1", "xDS · mesh CA"),
                                                   ("prometheus", "Deployment ×1", "merkez · 6 saat · remote_write alıcısı"),
                                                   ("grafana", "Deployment ×1", "NodePort 30300 → :3001 · org başına kategori"),
                                                   ("kiali", "Deployment ×1", "NodePort 30201 → :20001 · 3 cluster"),
                                                   ("ztunnel · istio-cni-node", "DaemonSet", "L4 mTLS · HBONE")], "mgmt") + 14
    y = ns_pods(d, c[2], y, cw, "logging-agent", [AGENTS[0]], "mgmt") + 14
    b3 = ns_pods(d, c[2], y, cw, "kyverno · metallb-system · kube-system", KUBE, "mgmt")
    d.flow([(380, 112), (380, 206)], "main")
    bot = max(b1, b2, b3) + 30
    d.boundary([(14, 96), (2186, 96), (2186, bot), (14, bot)], "kind-mgmt · kimlik, veri, gözlem · internete kapalı", "mgmt", fill_opacity=0.12)
    d.flow([(720, 223), (772, 223)], "main")
    d.flow([(1440, bot - 60), (1440, bot + 30)], "deny", "internet / host → mgmt servisleri (doğrudan): yol yok (yalnızca 3 port, localhost)", 1452, bot + 24)
    d.note(40, bot + 50, 1080, "Bu resimde", ["Lab'de kimlik, veri ve gözlem tek cluster'da (hedefte ayrı zone'lar): kaynak sınırı.",
                                          "mgmt'e her giriş istio-ingressgateway'den: SNI ve kaynak kimliğine göre (AuthorizationPolicy).",
                                          "Namespace'lerde allow-nothing: her servis yalnızca gateway'den ya da adı geçen servisten çağrılır.",
                                          "Log, metrik ve iz hattının tamamı: 07."], 12.5)
    d.legend(1140, bot + 50, 1040, [("identity", "kimlik"), ("data", "veri"), ("mgmt", "gözlem / platform"), ("dmz", "gateway")], extra=True, cols=3)
    d.save(out("06-mgmt-cluster.svg"), "06 · kind-mgmt: kimlik (Keycloak), veri (PostgreSQL, Valkey), gözlem ve giriş tablosu",
           "her kutu bir namespace · giriş tablosu: hangi ad / port hangi servise, kimden · Valkey'de önek başına kullanıcı", oy=OY)


# =====================================================================================================================
def img07():
    W, H, OY = 2200, 1250, 40
    d = D(W, H)
    # Sütunlar: kaynaklar → egress → mgmt girişi → depolar → görüntüleme
    cols = [(40, "Kaynaklar (her cluster)"), (520, "Çıkış (cluster başına)"), (940, "mgmt girişi"), (1300, "Depolar (mgmt)"), (1760, "Görüntüleme")]
    for x, t in cols:
        d.text(x, 128, t, 16, 700)
    d.boundary([(20, 150), (900, 150), (900, 900), (20, 900)], "dmz · cluster-a (aynı düzen) · mgmt", "internal", fill_opacity=0.08)
    d.boundary([(920, 150), (2180, 150), (2180, 900), (920, 900)], "kind-mgmt", "mgmt", fill_opacity=0.1)
    # Log
    d.pod(40, 180, 440, None, "fluent-bit", "DaemonSet · logging-agent", "mgmt", [
        ("fluent-bit 5.1", "agent", ["/var/log/pods/* + kube-apiserver audit", "Lua: kategori (apps, network, security,", "  db, infra) · cluster etiketi · maskeleme",
                                     "security kopyası (rewrite_tag)", "örnekleme: traceparent -01 izliyse tut"])], agent=True)
    d.pod(40, 400, 440, None, "edge-logs", "Docker · kind", "mgmt", [("fluent-bit", "agent", ["edge-lb · edge-waf · branch-fw", "doğrudan → logs-edge (mTLS)"])], agent=True)
    d.pod(40, 530, 440, None, "prometheus (agent modu)", "Deployment · istio-system", "mgmt", [
        ("prometheus", "agent", ["ztunnel, waypoint, gateway, istiod kazır", "yalnızca istio_* · pilot_* · up", "remote_write → prometheus-mgmt:80"])])
    d.pod(40, 700, 440, None, "gateway'ler · waypoint'ler (Envoy)", "Istio otel sağlayıcısı", "dmz", [
        ("istio-proxy", "proxy", ["span: OTLP/HTTP → traces-mgmt:80", "örnekleme %10 · x-client-trace-id: her zaman"])])
    eg = [(180, "logs-mgmt.istio-egress:80", "POST /loki/api/v1/push", "logs.mgmt.internal"),
          (550, "prometheus-mgmt.istio-egress:80", "POST /api/v1/write", "prometheus.mgmt.internal"),
          (720, "traces-mgmt.istio-egress:80", "POST /v1/traces", "traces.mgmt.internal")]
    for y, h, p, sni in eg:
        d.pod(520, y, 360, None, h, "egress listener", "dmz", [("egress gateway", "proxy", [p, "yalnızca POST · bu yol (AuthZ)", "→ " + sni + " :443 mTLS"])])
    d.pod(940, 180, 320, None, "istio-ingressgateway", "VIP .203.10", "dmz", [("Envoy", "proxy", ["SNI → hedef", "yalnızca egress kimlikleri", "logs-edge: MUTUAL (edge-logs)"])])
    d.pod(1300, 180, 420, None, "loki", "StatefulSet · logging", "mgmt", [("loki 3.7", "data", ["tenant = kategori (X-Scope-OrgID)", "apps · network · security · db · infra", "saklama 24 saat (compactor)"])])
    d.pod(1300, 530, 420, None, "prometheus (merkez)", "istio-system", "mgmt", [("prometheus", "data", ["remote_write alıcısı · 6 saat", "3 cluster'ın mesh metrikleri"])])
    d.pod(1300, 700, 420, None, "tempo", "StatefulSet · logging", "mgmt", [("tempo 2.10", "data", ["OTLP :4318 · izler", "trace_id ↔ log (Grafana)"])])
    d.pod(1760, 180, 400, None, "grafana", "NodePort → host :3001", "mgmt", [("grafana", "app", ["org başına kategori (RBAC)", "Apps · Network · Security · DB · Infra", "Main: korelasyon (log ↔ iz)",
                                                                                                  "Loki panoları (10a)"])])
    d.pod(1760, 530, 400, None, "kiali", "NodePort → host :20001", "mgmt", [("kiali", "app", ["mesh grafiği · 3 cluster", "uzak cluster API'si (token)"])])
    # akışlar
    d.flow([(480, 240), (520, 240)], "aux")
    d.flow([(880, 240), (940, 240)], "main")
    d.flow([(1260, 240), (1300, 240)], "main")
    d.flow([(480, 440), (910, 440), (910, 262), (940, 262)], "main", "logs-edge :443 mTLS", 700, 434)
    d.flow([(480, 590), (520, 590)], "aux")
    d.flow([(880, 610), (920, 610), (920, 274), (940, 274)], "main")
    d.flow([(1260, 262), (1280, 262), (1280, 590), (1300, 590)], "main")
    d.flow([(480, 760), (520, 760)], "aux")
    d.flow([(880, 780), (930, 780), (930, 286), (940, 286)], "main")
    d.flow([(1260, 278), (1270, 278), (1270, 760), (1300, 760)], "main")
    d.flow([(1720, 240), (1760, 240)], "req")
    d.flow([(1720, 760), (1740, 760), (1740, 280), (1760, 280)], "req")
    d.flow([(1720, 580), (1760, 580)], "req")
    d.note(40, 930, 1080, "Bu resimde", ["Gözlem verisi tek yönlü: cluster'lar mgmt'e yalnızca yazar (POST), mgmt'ten okuyamaz.",
                                          "Uygulama pod'ları mgmt'i görmez: log node'daki fluent-bit'ten, metrik agent'tan, iz Envoy'dan çıkar.",
                                          "Çıkış her cluster'da egress gateway'in düz HTTP :80 dinleyicisi; mgmt'e :443 mTLS ile taşır.",
                                          "Log ↔ iz: erişim logundaki trace_id Grafana'da Tempo'ya bağlanır."], 12.5)
    d.legend(1140, 930, 1040, [("mgmt", "agent / depo"), ("dmz", "gateway / Envoy")], extra=True, cols=3)
    d.save(out("07-gozlem-hatti.svg"), "07 · Gözlem hattı: log (Loki), metrik (Prometheus), iz (Tempo), görüntüleme (Grafana, Kiali)",
           "soldan sağa: üretici → cluster çıkışı → mgmt girişi → depo → ekran · gri kesikli: yerel toplama · mavi: zone geçişi (mTLS)", oy=OY)


# =====================================================================================================================
def img08():
    W, H, OY = 2200, 1280, 40
    d = D(W, H)
    d.boundary([(14, 96), (2186, 96), (2186, 910), (14, 910)], "BİR kind NODE'U = BİR DOCKER CONTAINER (ör. cluster-a-control-plane)", "internal", fill_opacity=0.1)
    d.node(30, 130, 1600, 760, "cluster-a-control-plane", "kindest/node v1.36 · containerd · kubelet :10250 · kindnet (CNI)")
    d.text(50, 186, "Kontrol düzlemi (static pod · kube-system) · lab'de aynı node'da", 14, 700)
    for i, (n, ls) in enumerate([("kube-apiserver", [":6443 · audit logu", "→ /var/log/kubernetes"]), ("etcd", ["cluster durumu", ":2379"]),
                                 ("controller-manager", ["ReplicaSet, Service", "Endpoint …"]), ("scheduler", ["pod → node", "(tek node)"])]):
        d.pod(50 + i * 392, 198, 380, None, n, "static pod", "external", [(n, "app", ls)])
    d.text(50, 330, "Uygulama pod'ları (sidecar yok)", 14, 700)
    d.pod(50, 344, 380, None, "web-bff (ns channel-bff)", "pod", "internal", [("bff", "app", [":8080 (yalnızca pod ağında)", "istek: http://account-api.account-api:8080"])])
    d.pod(442, 344, 380, None, "account-api (ns account-api)", "pod", "internal", [("api", "app", [":8080", "yalnızca waypoint'ten gelir"])])
    d.pod(834, 344, 380, None, "waypoint (ns account-api)", "pod", "dmz", [("istio-proxy (Envoy)", "proxy", ["in :15008 HBONE", "L7: JWT · AuthZ · canary · retry"])])
    d.pod(1226, 344, 384, None, "istio-egressgateway", "pod · istio-egress", "dmz", [("istio-proxy (Envoy)", "proxy", [":443 · :15432 · :16379 · :80", "→ mgmt (mTLS)"])])
    d.text(50, 480, "DaemonSet'ler ve platform pod'ları", 14, 700)
    d.pod(50, 494, 520, None, "ztunnel", "DaemonSet · istio-system", "mgmt", [("ztunnel (Rust)", "agent", [
        "in :15008 HBONE · gelen trafik pod'a :15006", "out :15001: pod'un çıkan trafiği buraya yönlenir",
        "pod başına SPIFFE sertifikası · L4 AuthZ · DNS :15053"])], agent=True)
    d.pod(590, 494, 500, None, "istio-cni-node", "DaemonSet · istio-system", "mgmt", [("install-cni + node agent", "agent", [
        "pod oluşunca pod ağına nftables kuralı", "pod trafiği → ztunnel (pod'a ayrıcalık yok)", "kindnet zincirine eklenir"])], agent=True)
    d.pod(1110, 494, 500, None, "fluent-bit", "DaemonSet · logging-agent", "mgmt", [("fluent-bit", "agent", [
        "/var/log/pods + audit (hostPath, salt okunur)", "Kyverno istisnası: yalnızca /var/log/", "→ egress :80 → mgmt Loki"])], agent=True)
    d.pod(50, 640, 380, None, "istiod", "Deployment · istio-system", "mgmt", [("discovery", "app", [":15012 xDS + CA (mTLS)", ":15017 webhook"])])
    d.pod(442, 640, 380, None, "prometheus (agent)", "Deployment · istio-system", "mgmt", [("prometheus", "agent", [":15020 / :15090 kazır", "→ egress → mgmt"])])
    d.pod(834, 640, 380, None, "kyverno", "4 Deployment · kyverno", "mgmt", [("admission-controller", "app", ["her pod: 6 politika", "imza: cosign anahtarı"])])
    d.pod(1226, 640, 384, None, "metallb speaker · kube-proxy · kindnet", "DaemonSet", "mgmt", [("node ağı", "agent", ["VIP'i duyurur (L2 / ARP)", "Service → pod (iptables)"])], agent=True)
    d.note(50, 780, 1560, "Pod'dan pod'a istek (numaralar)", [
        "1 web-bff, account-api'yi düz HTTP ile çağırır    2 istio-cni'nin kuralı bağlantıyı ztunnel'e (:15001) yönlendirir",
        "3 ztunnel: kaynak = web-bff'in SPIFFE kimliği; hedefin waypoint'i var → HBONE mTLS :15008 → waypoint",
        "4 waypoint (L7): iç JWT, AuthZ, canary, retry → HBONE → ztunnel    5 ztunnel: L4 politikası (yalnızca waypoint) → account-api :8080"], 12.5)
    d.text(1660, 150, "Portlar", 15, 700)
    ports = [(":8080", "uygulama (pod içi)"), (":15001", "ztunnel çıkış yakalama"), (":15006", "ztunnel giriş yakalama"), (":15008", "HBONE (mTLS tüneli)"),
             (":15012", "istiod xDS (mTLS)"), (":15017", "istiod webhook"), (":15020", "ztunnel / proxy metrik"), (":15021", "sağlık (gateway, waypoint)"),
             (":15053", "DNS proxy"), (":15090", "Envoy metrik"), (":6443", "kube-apiserver"), (":10250", "kubelet"),
             (":15432 / :16379", "egress → postgres / valkey"), (":443", "gateway'ler (zone geçişi)")]
    for i, (pt, desc) in enumerate(ports):
        y = 164 + i * 28
        d.n.append(f'<rect x="1660" y="{y}" width="500" height="24" rx="4" fill="{"#f4f7fc" if i % 2 else "#ffffff"}" stroke="#c4c4bf" stroke-width="0.8"/>')
        d.text(1670, y + 17, pt, 12.5, 700)
        d.text(1800, y + 17, desc, 12.5)
    d.box(1660, 570, 500, 150, "kind ile gerçek ortam farkı", ["Node bir Docker container'ı; içinde containerd.", "Kontrol düzlemi ve iş yükleri aynı node'da.",
                                                                "Gerçekte: ayrı master'lar, infra / worker", "havuzları, DC başına node'lar (prod 08)."], color="note", size=12)
    d.marker(44, 400, 1, "#2f7bd8")
    d.flow([(240, 440), (240, 494)], "main")
    d.marker(262, 504, 2, "#2f7bd8")
    d.flow([(450, 494), (450, 470), (1020, 470), (1020, 450)], "main", "HBONE :15008 → waypoint", 470, 464)
    d.marker(1040, 470, 3, "#2f7bd8")
    d.flow([(834, 400), (822, 400)], "main")
    d.marker(828, 380, 4, "#2f7bd8")
    d.marker(436, 400, 5, "#2f7bd8")
    d.legend(30, 940, 2150, [("internal", "uygulama"), ("dmz", "waypoint / gateway"), ("mgmt", "node agent / platform"), ("external", "kontrol düzlemi")],
             extra=True, cols=6)
    d.save(out("08-node-anatomisi.svg"), "08 · Bir kind node'unun anatomisi: kontrol düzlemi, pod'lar, DaemonSet agent'ları, ztunnel ve HBONE",
           "lab'de her cluster tek node: kontrol düzlemi ve iş yükleri aynı container'da · uygulama pod'unda sidecar yok · portlar sağda", oy=OY)


# =====================================================================================================================
def img09():
    W, H, OY = 2200, 1270, 40
    d = D(W, H)
    parts = [("mobile-sim", "public"), ("edge-lb + waf", "edge"), ("mobile-gateway", "dmz"), ("auth-service", "dmz"), ("Valkey · cihaz", "data"),
             ("Keycloak", "identity"), ("dmz-egressgw", "dmz"), ("ingressgw (a)", "internal"), ("mobile-bff", "internal"),
             ("account-api", "internal"), ("PostgreSQL", "data")]
    x0, dx = 100, 198
    xs = [x0 + i * dx for i in range(len(parts))]
    top, bot = 120, 1060
    for x, (n, c) in zip(xs, parts):
        fill, stroke, tcol = PALETTE[c]
        d.n.append(f'<rect x="{x - 90}" y="{top}" width="180" height="44" rx="8" fill="{fill}" stroke="{stroke}" stroke-width="1.6"/>')
        d.text(x, top + 28, n, 13.5, 700, tcol, "middle")
        d.e.append(f'<line x1="{x}" y1="{top + 44}" x2="{x}" y2="{bot}" stroke="{stroke}" stroke-width="1.4" stroke-dasharray="5 5"/>')
    steps = [(0, 1, "main", "POST mobile-api.apps.example.local:8443/mobile/v1/accounts/1/transfers", "DPoP + attestation başlıkları · TLS (edge-lb) · OWASP CRS (edge-waf)"),
             (1, 2, "main", "VIP .200.11:443 mTLS (Edge-DMZ CA)", "header temizliği · x-channel=mobile · 30 rps"),
             (2, 3, "req", "ext_authz (HBONE → auth waypoint → :8080)", "DPoP: htm / htu / ath / iat · attestation: imza, bütünlük, sürüm ≥ 3.0.0"),
             (3, 4, "req", "jti SET NX (dpop:) · cihaz lookup (egress → mgmt)", "aynı kanıt ikinci kez → 401 · anahtar bu kullanıcıya kayıtlı değil → 403"),
             (3, 5, "req", "introspection + token exchange (egress → keycloak.mgmt.internal)", "aktif mi? → iç JWT: 2 dk · channel=mobile · scope · sid · loa_map"),
             (5, 3, "ret", "iç JWT (Keycloak imzalı)", ""),
             (3, 2, "ret", "izin + x-user-jwt", "ret olsaydı 401 / 403 / 426 burada döner"),
             (2, 6, "main", "/mobile/v1 öneki kaldırılır · Host mobile-bff.apps.example.local", "dış DPoP token'ı silinir · yalnızca iç JWT taşınır"),
             (6, 7, "main", "zone geçişi: VIP .201.10:443 (ISTIO_MUTUAL)", "kaynak = dmz-egressgateway · JWT imzası (Keycloak JWKS)"),
             (7, 8, "main", "HBONE → channel-bff waypoint → mobile-bff :8080", "issuer customers · channel=mobile"),
             (8, 9, "main", "HBONE → account-api waypoint → v1 / v2 :8080", "seviye 2 son 5 dk (mobile-bff) · write rotası: retry yok, 5 sn"),
             (9, 10, "main", "INSERT transfer · egress :15432 → :5432", "BOLA: hesap bu kullanıcının mı? · servis başına DB rolü"),
             (9, 0, "ret", "202 Accepted · tüm hop'lar aynı request_id / trace_id", "erişim logları → Loki · span'ler → Tempo (07)")]
    y = top + 84
    for i, (a, b, kind, lab, sub) in enumerate(steps):
        xa, xb = xs[a], xs[b]
        d.flow([(xa, y), (xb, y)], "aux" if kind == "ret" else kind)
        mx = min(xa, xb)
        d.marker(mx + 2, y - 18, i + 1, "#2f7bd8" if kind == "main" else ("#5f5f5a" if kind == "ret" else "#c2410c"))
        d.text(mx + 22, y - 12, lab, 12.5, 600)
        if sub:
            d.text(mx + 22, y + 14, sub, 11.5, 400, "#5f5f5a")
        y += 64
    d.note(40, 1090, 1050, "Nasıl okunur", ["Sütunlar istekten geçen bileşenler (renk = zone), yukarıdan aşağı zaman.",
                                             "Mavi: mTLS ana akış · turuncu: kontrol / yardımcı çağrı · gri kesikli: yanıt.",
                                             "Ayrıntılar: Docker 01 · DMZ 02-03 · cluster-a 04-05 · mgmt 06 · gözlem 07 · node 08."], 12.5)
    d.legend(1110, 1090, 1070, [("public", "istemci"), ("edge", "edge"), ("dmz", "DMZ"), ("identity", "kimlik"), ("internal", "internal"),
                               ("data", "veri")], extra=False, cols=3)
    d.save(out("09-uctan-uca-mobil-transfer.svg"), "09 · Uçtan uca istek (demo): mobil uygulamadan para transferi, adım adım",
           "her adım: kimden → kime · port / protokol · yapılan kontrol · gerçek adlar ve portlar (08-verify.sh'in sınadığı yol)", oy=OY)


IMAGES = {"00": img00, "01": img01, "02": img02, "03": img03, "04": img04, "05": img05, "06": img06, "07": img07, "08": img08, "09": img09}

if __name__ == "__main__":
    for k in (sys.argv[1:] or IMAGES):
        IMAGES[k]()
        print("ok", k)
