"""Zone iç yapısı görselleri (prod hedef + lab karşılığı): zone-edge, zone-dmz, zone-sube, zone-kimlik, zone-internal.
Çalıştırma: python docs/images/src/zone_images.py  (SVG üretir; PNG için README.md'deki komut)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from topo_style import Diagram

HERE = os.path.dirname(os.path.abspath(__file__))
W = 1340
X0, X1 = 40, 1300            # zone kenarları
PAD = 25                     # zone içi kenar boşluğu
GAP_X, GAP_Y = 20, 62        # kutular arası


def box_h(lines):
    return 52 + 26 * max(len(lines), 1)


def render(name, title, subtitle, incoming, zone_title, rows, edges, outgoing, out_edges, controls, lab, in_edges=None):
    """rows: [[(başlık, satırlar, planlı?), ...], ...]
    edges: [(satır, kutu, satır, kutu, etiket, mavi?, kesikli?)]  kutular arası oklar
    incoming / outgoing: [(başlık, alt başlık, planlı?)]
    in_edges: [(gelen_index, satır0 kutu_index, etiket)]; out_edges: [(satır, kutu, giden_index, etiket, mavi?)]"""
    y = 110
    d = Diagram(W, 100)

    def row_layout(n, top, inner_x0=X0 + PAD, inner_x1=X1 - PAD):
        w = (inner_x1 - inner_x0 - GAP_X * (n - 1)) / n
        return [(inner_x0 + i * (w + GAP_X), top, w) for i in range(n)]

    # Gelenler
    in_pos = row_layout(len(incoming), y, X0, X1)
    for (t, sub, pl), (x, yy, w) in zip(incoming, in_pos):
        d.channel(x, yy, w, t, sub, planned=pl)
    y += 78 + 60

    # Zone ve satırlar
    zone_top = y
    y += 60
    pos = []
    for row in rows:
        h = max(box_h(lines) for _, lines, _ in row)
        lay = row_layout(len(row), y)
        pos.append([(x, y, w, h) for (x, _, w) in lay])
        y += h + GAP_Y
    zone_bottom = y - GAP_Y + 25
    d.zone(X0, zone_top, X1 - X0, zone_bottom - zone_top, zone_title, title_above=True)
    for row, prow in zip(rows, pos):
        for (t, lines, pl), (x, yy, w, h) in zip(row, prow):
            d.box(x, yy, w, h, t, lines, planned=pl)

    # Gidenler
    y = zone_bottom + 60
    out_pos = row_layout(len(outgoing), y, X0, X1) if outgoing else []
    for (t, sub, pl), (x, yy, w) in zip(outgoing, out_pos):
        d.channel(x, yy, w, t, sub, planned=pl)
    y += (78 + 50) if outgoing else 10

    # Kontroller + lab karşılığı
    hb = max(box_h(controls), box_h(lab))
    half = (X1 - X0 - GAP_X) / 2
    d.box(X0, y, half, hb, "Kontroller", controls)
    d.box(X0 + half + GAP_X, y, half, hb, "Lab karşılığı", lab)
    y += hb + 30

    # Oklar
    def cx(x, w, k=0, n=1):
        return x + w * (k + 1) / (n + 1)

    for i, j, lab_txt in (in_edges or [(k, min(k, len(rows[0]) - 1), None) for k in range(len(incoming))]):
        x, yy, w = in_pos[i]
        bx, by, bw, bh = pos[0][j]
        sx, ex = x + w / 2, bx + bw / 2
        mid = yy + 78 + 30   # yatay kısım zone'un dışında (başlığı kesmesin)
        pts = [(sx, yy + 78), (sx, mid), (ex, mid), (ex, by)] if abs(sx - ex) > 2 else [(sx, yy + 78), (ex, by)]
        d.arrow(pts, label=lab_txt, lx=sx + 8, ly=yy + 78 + 30)
    for r1, b1, r2, b2, lab_txt, blue, dashed in edges:
        x1, y1, w1, h1 = pos[r1][b1]
        x2, y2, w2, h2 = pos[r2][b2]
        if r1 == r2:   # aynı satırda yatay
            if x2 > x1:
                pts = [(x1 + w1, y1 + h1 / 2), (x2, y1 + h1 / 2)]
            else:
                pts = [(x1, y1 + h1 / 2), (x2 + w2, y1 + h1 / 2)]
            d.arrow(pts, blue=blue, dashed=dashed)
            if lab_txt:
                d.t((pts[0][0] + pts[1][0]) / 2, y1 + h1 / 2 - 8, lab_txt, 13.5, 400, "#5f5f5a", "middle", d.l)
            continue
        sx = min(max(x2 + w2 / 2, x1 + 30), x1 + w1 - 30)   # mümkünse düz in
        ex = min(max(sx, x2 + 30), x2 + w2 - 30)
        top = y1 + h1
        mid = top + GAP_Y / 2
        pts = [(sx, top), (ex, y2)] if abs(sx - ex) < 2 else [(sx, top), (sx, mid), (ex, mid), (ex, y2)]
        d.arrow(pts, blue=blue, dashed=dashed, label=lab_txt, lx=ex + 8, ly=mid + 5)
    for r, b, k, lab_txt, blue in out_edges:
        x, yy, w, h = pos[r][b]
        ox, oy, ow = out_pos[k]
        sx, ex = x + w / 2, ox + ow / 2
        mid = zone_bottom + 30
        pts = [(sx, yy + h), (sx, mid), (ex, mid), (ex, oy)] if abs(sx - ex) > 2 else [(sx, yy + h), (ex, oy)]
        d.arrow(pts, blue=blue, label=lab_txt, lx=ex + 8, ly=oy - 10)

    d.h = int(y)
    d.save(os.path.join(HERE, "..", f"{name}.svg"), title, subtitle)
    print("ok", name, d.h)
    return d.h


# =================================================================== EDGE
render(
    "zone-edge", "Edge zone · iç yapı (prod hedef)",
    "İnternetten gelen trafiğin ilk karşılandığı yer: DDoS, DNS, TLS, WAF. İş mantığı ve veri yok.",
    [("Mobil", "m-api.banka.com.tr", False), ("Web", "ib.banka.com.tr", False), ("Partner", "api.banka.com.tr", False)],
    "Edge zone (dış DMZ)",
    [
        [("ISS / DDoS koruma", ["upstream scrubbing (ISS + bulut)", "BGP anycast · L3/L4 hacim saldırısı", "otomatik trafik yönlendirme"], False),
         ("GSLB (DNS)", ["DC1 / DC2 sağlık kontrolü", "aktif-aktif · coğrafi yönlendirme", "DNSSEC"], False),
         ("CDN / bulut WAF", ["statik içerik (web)", "L7 DDoS · bot sınıflandırma", "(opsiyonel)"], False)],
        [("Perimeter firewall (NGFW)", ["yalnızca 443/TCP", "IPS · geo-IP · itibar listeleri", "DC başına HA çift"], False)],
        [("F5 BIG-IP LTM (DC başına HA)", ["TLS 1.2+/1.3 sonlandırma (anahtar HSM'de)", "HSTS · 301 · bağlantı/istek sınırı (IP)",
          "partner: istemci sertifikası (mTLS)", "Host → kanal VIP'i (iRule)", "DMZ'ye yeniden şifreleme (mTLS)"], False),
         ("F5 Advanced WAF + bot koruma", ["imza + OWASP kuralları · paranoia ayarı", "bot / credential stuffing koruması",
          "header temizliği (X-Forwarded-*, x-user-jwt)", "hata sayfası maskeleme (5xx)", "önce izleme, sonra engelleme modu"], False)],
    ],
    [(0, 0, 1, 0, None, False, False), (0, 1, 1, 0, None, False, False), (0, 2, 1, 0, None, False, False),
     (1, 0, 2, 0, None, False, False), (2, 0, 2, 1, "inspection", False, False)],
    [("DMZ zone", "web · mobile · partner gateway VIP'leri (iç firewall)", False)],
    [(2, 1, 0, "mTLS (Edge-DMZ CA)", True)],
    ["DDoS: hacim (ISS) + uygulama (CDN/WAF)", "TLS: yalnızca 1.2+/1.3, modern şifreler, HSTS", "IP başına istek ve bağlantı sınırı, slow-loris koruması",
     "dışarıdan gelen kimlik/proxy header'ları silinir", "DMZ'ye yalnızca edge'in istemci sertifikasıyla bağlanılır"],
    ["edge-lb (HAProxy 3.0): TLS, HSTS, hız sınırı, header", "  temizliği, partner sertifikası (crt-list), 5xx maskesi", "edge-waf (ModSecurity + CRS 4): WAF, Host → kanal",
     "  gateway'i, DMZ'ye mTLS (Edge-DMZ Zone CA)", "Yok (kapsam dışı): DDoS, GSLB, CDN, NGFW"],
    in_edges=[(0, 0, None), (1, 1, None), (2, 2, None)],
)

# =================================================================== DMZ
render(
    "zone-dmz", "DMZ zone · iç yapı (prod hedef, DC başına)",
    "Kanal başına kapı, kimlik doğrulama ve token exchange. Internal'a tek kapı: dmz-egressgw. İş mantığı ve veri yok.",
    [("Edge (F5)", "web · mobile · partner · mTLS (Edge-DMZ CA)", False)],
    "DMZ zone · ocp-dmz-a / ocp-dmz-b",
    [
        [("web-gw", ["Host www · CORS (yalnızca kendi origin)", "x-channel=web · local rate limit"], False),
         ("mobile-gw", ["/mobile/v1/* · x-channel=mobile", "uygulama doğrulama (attestation)"], False),
         ("partner-gw", ["izin listesi · /partner/v1/*", "token ↔ sertifika bağı · global kota"], False)],
        [("web-bff · token handler", ["oturum cookie'si (HttpOnly, Secure, SameSite)", "CSRF · CSP · güvenlik header'ları",
          "tarayıcıya token verilmez"], False),
         ("auth-service (ext_authz, token exchange)", ["her kanal gateway'i her isteği buraya sorar", "dış token: imza, iss, aud, exp (IdP JWKS)",
          "kanal ↔ realm/client/sertifika kuralı", "iç JWT: RS256, 5 dk, jti · anahtar HSM'de"], False),
         ("ratelimit + dmz-redis", ["partner / kullanıcı başına kota", "jti tekrar kullanım önbelleği", "fail-open; local limit korur"], False)],
        [("consent kontrolü (açık bankacılık)", ["consent ID token'a bağlı", "consent-svc (Kimlik zone)"], False),
         ("dmz-egressgw · internal'a tek kapı", ["girenler: web-bff, mobile-gw, partner-gw", "AuthZ: port + kimlik · mTLS (ISTIO_MUTUAL)",
          "Authorization silinir, x-user-jwt taşınır"], False)],
    ],
    [(0, 0, 1, 0, None, False, False), (0, 1, 1, 1, "ext_authz", False, True), (0, 2, 1, 2, "kota", False, True),
     (1, 0, 2, 1, None, False, False), (1, 1, 2, 0, None, False, True)],
    [("Kimlik zone", "OIDC · JWKS · consent-svc", False), ("Internal zone", "int-ingressgw · mTLS + iç JWT", False)],
    [(2, 0, 0, None, False), (2, 1, 1, "mTLS + iç JWT", True)],
    ["kanal başına ayrı gateway, namespace, secret, kota", "her istek ext_authz'den geçer (failOpen: false)", "dış token içeri girmez; iç JWT 5 dk, DMZ imzalı",
     "sahte x-channel / x-partner-id / x-user-jwt ezilir", "internal'a yalnızca egress'ten; web gateway doğrudan çıkamaz"],
    ["kind-dmz: dmz-ingressgateway (web), mobile-, partner-,", "  branch-gateway · ext_authz (4 sağlayıcı)", "auth-service (Go) · web-bff (Go) · ratelimit (Envoy)",
     "dmz-egressgateway (port + kimlik AuthZ)", "Yok: token handler cookie, attestation, consent (09b)"],
    in_edges=[(0, 0, None), (0, 1, None), (0, 2, None)],
)

# =================================================================== ŞUBE
render(
    "zone-sube", "Şube zone · iç yapı (prod hedef)",
    "Şube personeli ve cihazları kurum WAN'ından gelir; internet edge'inden geçmez. Kimlik: personel + cihaz.",
    [("Gişe / operasyon PC'leri", "yönetilen cihaz · cihaz sertifikası", False), ("Şube LAN", "802.1X / NAC · yazıcı, imza ped'i", False)],
    "Şube zone",
    [
        [("Şube router (SD-WAN CPE)", ["IPsec overlay · çift hat (MPLS + internet)", "segmentasyon: personel / misafir / cihaz"], False),
         ("Cihaz yönetimi (MDM / SCEP)", ["cihaz sertifikası dağıtımı ve yenileme", "kayıp/çalıntı cihaz iptali (CRL/OCSP)"], False)],
        [("SD-WAN hub (DC1 / DC2)", ["şube tünellerinin sonlandığı yer", "QoS · yol seçimi"], False),
         ("branch-fw (NGFW)", ["yalnızca branch-gw:443 ve izinli servisler", "IPS · şube başına bağlantı sınırı"], False)],
        [("Personel kimliği", ["AD / LDAP → Keycloak staff realm", "MFA: OTP veya akıllı kart", "rol: gişe · operasyon · yönetici"], False),
         ("branch-gw (A/B)", ["mTLS: cihaz sertifikası (Branch CA)", "XFCC → cihaz kimliği · x-channel=branch",
          "ext_authz: personel token'ı (staff realm)", "yalnızca /branch/v1/* · kota"], False)],
    ],
    [(0, 0, 1, 0, None, False, False), (1, 0, 1, 1, None, False, False), (1, 1, 2, 1, "TLS passthrough", False, False),
     (2, 0, 2, 1, "token", False, True)],
    [("Kimlik zone", "staff realm · AD SSO", False), ("Internal zone", "mTLS + iç JWT (personel + cihaz)", False)],
    [(2, 0, 0, None, False), (2, 1, 1, "mTLS + iç JWT", True)],
    ["internetten erişim yok; şube ağından yalnızca branch-gw", "her istekte iki kimlik: cihaz sertifikası + personel token'ı", "iç JWT'de şube/cihaz bilgisi (denetim izi)",
     "MFA zorunlu (test kullanıcısı hariç: lab)", "rol bazlı yetki ve onay limitleri internal'da"],
    ["branch-net (Docker ağı) · branch-terminal (sube-0001)", "branch-fw (HAProxy TCP, yalnızca .200.13:443)", "branch-gateway (DMZ cluster'ında): Branch CA, XFCC,",
     "  ext_authz (auth-branch), /sso/realms/staff/*", "Yok: SD-WAN, NAC, MDM, AD federasyonu"],
    in_edges=[(0, 0, None), (1, 0, None)],
)

# =================================================================== KİMLİK
render(
    "zone-kimlik", "Kimlik zone · iç yapı (prod hedef)",
    "Müşteri, partner ve personel kimliği. Token'ları yalnızca IdP verir; içeride geçerli olan DMZ'nin iç JWT'sidir.",
    [("DMZ (auth-service)", "JWKS · introspection", False), ("Kullanıcı / partner", "login · token (edge → DMZ)", False), ("Şube (branch-gw)", "personel login", False)],
    "Kimlik zone",
    [
        [("Keycloak / RHBK (A/B)", ["Infinispan kümesi · iki DC", "realm anahtarları HSM'de", "yönetim konsolu yalnızca bastion/PAM"], False)],
        [("customers realm", ["web-bff, mobile-app: auth code + PKCE", "brute force · adaptif kimlik doğrulama", "step-up (acr) · cihaz bağlama"], False),
         ("partners realm", ["client credentials", "private_key_jwt / mTLS bağlı token", "client başına scope ve kota"], False),
         ("staff realm", ["AD / LDAP federasyonu", "MFA (OTP, akıllı kart)", "rol: gişe · operasyon"], False)],
        [("device-registry", ["mobil cihaz kaydı ve bağlama", "cihaz iptali"], False),
         ("consent-svc", ["açık bankacılık rızaları", "hesap · izin · süre · geri alma"], False),
         ("redis-session (A/B)", ["oturum / önbellek", "replikasyonlu"], False),
         ("IdP veritabanı", ["PostgreSQL HA", "şifreli · yedekli"], False)],
    ],
    [(0, 0, 1, 0, None, False, False), (0, 0, 1, 1, None, False, False), (0, 0, 1, 2, None, False, False),
     (1, 0, 2, 0, None, False, True), (1, 1, 2, 1, None, False, True)],
    [("Çıktı: dış access token (5 dk)", "DMZ'deki auth-service doğrular; içeri DMZ'nin imzaladığı iç JWT girer", False)],
    [],
    ["first-party client'larda consent yok; üçüncü taraf: consent-svc", "client başına en az yetki (fullScopeAllowed: false)", "kısa ömürlü token (5 dk), brute force koruması",
     "yönetim konsolu dışarıya kapalı", "internal servisler IdP'ye bağlanmaz (inline JWKS)"],
    ["Keycloak 26.8 (optimize image) · mgmt/iam", "realm: customers, partners, staff · scope eşlemeleri", "PostgreSQL (mgmt/data) · OTP politikası (staff)",
     "/admin ve master realm kapalı (DMZ + mgmt AuthZ)", "Yok: HA, HSM, AD, device-registry, consent (09b)"],
    in_edges=[(0, 0, None), (1, 0, None), (2, 0, None)],
)

# =================================================================== INTERNAL
render(
    "zone-internal", "Internal zone · iç yapı (prod hedef, DC başına)",
    "Kanaldan bağımsız iş servisleri. Giriş yalnızca DMZ egress, şube ve kart zone kimliklerinden; her istekte iç JWT.",
    [("DMZ zone", "dmz-egressgw · mTLS + iç JWT", False), ("Şube zone", "branch-gw · mTLS + iç JWT", False), ("Kart zone (PCI)", "mTLS · token PAN", False)],
    "Internal zone · ocp-int-a / ocp-int-b",
    [
        [("int-ingressgw (MUTUAL TLS)", ["AuthZ: yalnızca dmz-egress, branch-gw, kart zone", "RequestAuthentication: iç JWT (inline JWKS)",
          "JWT'siz istek reddedilir"], False)],
        [("account · customer", ["waypoint: rol + kanal + sub (BOLA)", "yalnızca okuma uçları GET"], False),
         ("transfer · payments", ["step-up (acr) · idempotency key", "limit kontrolü · fraud sorgusu"], False),
         ("card · fraud · notification", ["PAN yerine token (tokenization)", "olay tabanlı (Kafka)"], False)],
        [("Service mesh (ambient)", ["ztunnel: mTLS (HBONE), L4 varsayılan reddet", "waypoint: L7 AuthZ, JWT, claim kuralları",
          "uygulama header'ı taşır: x-user-jwt"], False),
         ("int-egressgw", ["→ core banking (mTLS)", "→ data zone (TCP, mTLS)", "→ dış kurumlar (EFT/FAST, SWIFT)", "port + waypoint kimliği bazlı AuthZ"], False)],
    ],
    [(0, 0, 1, 0, None, False, False), (0, 0, 1, 1, None, False, False), (0, 0, 1, 2, None, False, False),
     (1, 0, 2, 1, None, False, False), (1, 1, 2, 1, None, False, False), (1, 2, 2, 1, None, False, False)],
    [("Core banking zone", "core-ingressgw · mTLS", False), ("Data zone", "PostgreSQL · Kafka · cache", False), ("Dış kurumlar", "TCMB · SWIFT · KKB", False)],
    [(2, 1, 0, None, True), (2, 1, 1, None, True), (2, 1, 2, None, False)],
    ["giriş yalnızca bilinen zone kimliklerinden + iç JWT", "namespace başına varsayılan reddet (allow-nothing)", "politikalar Service'e bağlı (waypoint geneline değil)",
     "servis başına DB kullanıcısı; uygulama mgmt/data adresini bilmez", "imzalı image (Kyverno) · restricted Pod Security"],
    ["kind-cluster-a: istio-ingressgateway (dmz-egress + iç JWT)", "api-a (podinfo) + waypoint · account-api (Go) + waypoint", "RequestAuthentication (ingress + waypoint'ler)",
     "istio-egressgateway: httpbin, :15432 PostgreSQL, :16379 Valkey", "Yok: core banking, Kafka, kart zone, step-up (09)"],
    in_edges=[(0, 0, None), (1, 0, None), (2, 0, None)],
)
