"""Ayrıntılı prod topolojisi seti (docs/images/prod-detay/) için çizim yardımcıları.
topo_style.Diagram'ı genişletir: namespace / node / pod / container kutuları, giriş-çıkış (port) rozetleri,
numaralı işaretler ve ortak lejant."""
from xml.sax.saxutils import escape

from topo_style import BLUE, FONT, GRAY, PALETTE, SUB, TXT, Diagram

IN_C, OUT_C, DENY_C = "#1d7a46", "#c2410c", "#b91c1c"

# Container türleri: (zemin, kenar, etiket)
CTYPE = {
    "app":   ("#eaf2fd", "#6d9fe4", "uygulama"),
    "proxy": ("#fff1e0", "#e39b62", "proxy (Envoy)"),
    "agent": ("#e8f5e8", "#6abd6a", "agent"),
    "data":  ("#f3ecfb", "#a383e0", "veri"),
    "init":  ("#f2f2f2", "#a3a3a3", "init / iş"),
    "ext":   ("#f7f7f5", "#a3a3a3", "harici"),
}


class D(Diagram):
    def text(self, x, y, s, size=14, weight=400, color=TXT, anchor="start"):
        self.t(x, y, s, size, weight, color, anchor, self.l)

    def nsbox(self, x, y, w, h, title, color, sub=None):
        """Namespace çerçevesi: renkli başlık şeridi, ince kesikli kenar"""
        fill, stroke, tcol = PALETTE[color]
        self.z.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="9" fill="#ffffff" fill-opacity="0.82" '
                      f'stroke="{stroke}" stroke-width="1.5" stroke-dasharray="5 4"/>')
        self.z.append(f'<rect x="{x}" y="{y}" width="{w}" height="28" rx="9" fill="{fill}"/>')
        self.t(x + 12, y + 19, "ns " + title, 14, 700, tcol, layer=self.z)
        if sub:
            self.t(x + w - 10, y + 19, sub, 12, 400, SUB, "end", self.z)

    def node(self, x, y, w, h, title, sub=None):
        """Node (sunucu): koyu düz kenar"""
        self.z.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="#fbfbfa" stroke="#55554f" stroke-width="2"/>')
        self.z.append(f'<rect x="{x}" y="{y}" width="{min(w, len(title) * 8.4 + 56)}" height="26" rx="6" fill="#55554f"/>')
        self.t(x + 10, y + 18, "▣ " + title, 13.5, 700, "#ffffff", layer=self.z)
        if sub:
            self.t(x + w - 10, y + 18, sub, 12, 400, SUB, "end", self.z)

    def pod(self, x, y, w, h, name, kind, color, containers=(), agent=False):
        """Pod: başlık (ad + iş yükü türü), içinde container'lar. agent=True: DaemonSet (her node'da bir tane)"""
        stroke = PALETTE[color][1]
        dash = ' stroke-dasharray="4 3"' if agent else ""
        if h is None:   # yükseklik içeriğe göre
            h = 34 + sum(22 + 17 * len(c[2] if len(c) > 2 else ()) + 5 for c in containers)
        self.n.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="#ffffff" stroke="{stroke}" stroke-width="1.8"{dash}/>')
        self.t(x + 10, y + 19, ("⬡ " if agent else "◼ ") + name, 13.5, 700, TXT)
        if kind:
            self.t(x + w - 8, y + 19, kind, 11.5, 400, SUB, "end")
        cy = y + 28
        for c in containers:
            cname, ctype = c[0], c[1]
            lines = c[2] if len(c) > 2 else ()
            ch = 22 + 17 * len(lines)
            self.container(x + 8, cy, w - 16, ch, cname, ctype, lines)
            cy += ch + 5
        return y + h   # pod'un alt kenarı

    def container(self, x, y, w, h, name, ctype, lines=()):
        fill, stroke, _ = CTYPE[ctype]
        dash = ' stroke-dasharray="4 3"' if ctype == "init" else ""
        self.n.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="5" fill="{fill}" stroke="{stroke}" stroke-width="1.2"{dash}/>')
        self.t(x + 8, y + 15, name, 12.5, 600, TXT)
        for i, ln in enumerate(lines):
            self.t(x + 8, y + 32 + i * 17, ln, 11.5, 400, "#3a3a3a")

    def box(self, x, y, w, h, title, lines=(), color=None, fill="#ffffff", size=13):
        """Küçük bileşen kutusu (cluster dışı cihaz, VM, appliance)"""
        stroke = PALETTE[color][1] if color else "#c4c4bf"
        self.n.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="{fill}" stroke="{stroke}" stroke-width="1.6"/>')
        self.t(x + 10, y + 20, title, size + 1, 700, TXT)
        for i, ln in enumerate(lines):
            self.t(x + 10, y + 40 + i * 18, ln, size - 1, 400, "#2b2b2b")

    def badge(self, x, y, text, kind="in", anchor="start"):
        """Giriş / çıkış rozeti: in = yeşil ◀ (dışarıdan gelen), out = turuncu ▶ (dışarıya giden), deny = kırmızı ✕"""
        col = {"in": IN_C, "out": OUT_C, "deny": DENY_C}[kind]
        glyph = {"in": "⇥ ", "out": "↦ ", "deny": "✕ "}[kind]
        s = glyph + text
        w = len(s) * 6.9 + 16
        bx = x if anchor == "start" else x - w
        self.l.append(f'<rect x="{bx}" y="{y - 13}" width="{w}" height="19" rx="9.5" fill="#ffffff" stroke="{col}" stroke-width="1.5"/>')
        self.l.append(f'<text x="{bx + 8}" y="{y + 1}" font-family="{FONT}" font-size="11.5" font-weight="700" fill="{col}">{escape(s)}</text>')
        return w

    def marker(self, x, y, n, color="#1f1f1f"):
        """Numaralı işaret (adım ya da ayrıntı resmi numarası)"""
        self.l.append(f'<circle cx="{x}" cy="{y}" r="13" fill="{color}"/>')
        self.l.append(f'<text x="{x}" y="{y + 5}" font-family="{FONT}" font-size="13" font-weight="700" fill="#ffffff" text-anchor="middle">{escape(str(n))}</text>')

    def link(self, x, y, label):
        """"Ayrıntı: resim NN" etiketi"""
        w = len(label) * 7.2 + 18
        self.l.append(f'<rect x="{x}" y="{y - 14}" width="{w}" height="21" rx="10.5" fill="#1f1f1f"/>')
        self.l.append(f'<text x="{x + 9}" y="{y + 1}" font-family="{FONT}" font-size="12.5" font-weight="700" fill="#ffffff">{escape(label)}</text>')

    def flow(self, pts, kind="main", label=None, lx=None, ly=None, anchor="start"):
        """Akış oku: main (mavi kalın: mTLS ana akış), req (gri), aux (gri kesikli), deny (kırmızı kesikli, yasak)"""
        if kind == "deny":
            d = "M " + " L ".join(f"{a},{b}" for a, b in pts)
            self.e.append(f'<path d="{d}" fill="none" stroke="{DENY_C}" stroke-width="2" stroke-dasharray="5 4" marker-end="url(#ad)"/>')
            if label:
                self.t(lx, ly, label, 12.5, 600, DENY_C, anchor, self.l)
            return
        self.arrow(pts, blue=(kind == "main"), dashed=(kind == "aux"))
        if label:
            for i, part in enumerate(label.split("\n")):
                self.t(lx, ly + i * 17, part, 12.5, 600 if kind == "main" else 400, "#1f1f1f" if kind == "main" else SUB, anchor, self.l)

    def note(self, x, y, w, title, lines, size=13):
        h = 34 + len(lines) * (size + 6)
        self.n.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="#fffdf3" stroke="#d8cfa3" stroke-width="1.3"/>')
        self.t(x + 12, y + 22, title, size + 1, 700, TXT)
        for i, ln in enumerate(lines):
            self.t(x + 12, y + 44 + i * (size + 6), ln, size, 400, "#2b2b2b")
        return h

    def legend(self, x, y, w, zones=(), extra=True, cols=4):
        """Ortak lejant: zone renkleri + gösterim öğeleri"""
        items = [("zone", z, lbl) for z, lbl in zones]
        if extra:
            items += [("bound", None, "güven sınırı (kalın kesikli)"), ("ns", None, "namespace"), ("node", None, "node (sunucu)"),
                      ("pod", None, "pod (Deployment / StatefulSet)"), ("agentpod", None, "DaemonSet pod (her node'da)"),
                      ("c-app", None, "container: uygulama"), ("c-proxy", None, "container: Envoy proxy"), ("c-agent", None, "container: agent"),
                      ("c-data", None, "container: veri"), ("main", None, "ana akış (mTLS)"), ("req", None, "istek / bağlantı"),
                      ("aux", None, "yardımcı akış (log, metrik, kontrol)"), ("deny", None, "yasak yol"), ("in", None, "giriş: port / protokol"),
                      ("out", None, "çıkış: hedef port / protokol"), ("mark", None, "adım / ayrıntı numarası")]
        rows = (len(items) + cols - 1) // cols
        h = 44 + rows * 28
        self.n.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="#fafaf8" stroke="#c4c4bf" stroke-width="1.2"/>')
        self.t(x + 14, y + 24, "Lejant", 15, 700, TXT)
        cw = (w - 28) / cols
        for i, (k, z, lbl) in enumerate(items):
            cx = x + 14 + (i % cols) * cw
            cy = y + 46 + (i // cols) * 28
            if k == "zone":
                fill, stroke, _ = PALETTE[z]
                self.n.append(f'<rect x="{cx}" y="{cy - 12}" width="30" height="17" rx="4" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>')
            elif k == "bound":
                self.n.append(f'<line x1="{cx}" y1="{cy - 4}" x2="{cx + 30}" y2="{cy - 4}" stroke="#6d9fe4" stroke-width="3" stroke-dasharray="9 5"/>')
            elif k == "ns":
                self.n.append(f'<rect x="{cx}" y="{cy - 12}" width="30" height="17" rx="4" fill="#ffffff" stroke="#6d9fe4" stroke-width="1.4" stroke-dasharray="5 4"/>')
            elif k == "node":
                self.n.append(f'<rect x="{cx}" y="{cy - 12}" width="30" height="17" rx="3" fill="#fbfbfa" stroke="#55554f" stroke-width="2"/>')
            elif k in ("pod", "agentpod"):
                dash = ' stroke-dasharray="4 3"' if k == "agentpod" else ""
                self.n.append(f'<rect x="{cx}" y="{cy - 12}" width="30" height="17" rx="4" fill="#ffffff" stroke="#6d9fe4" stroke-width="1.8"{dash}/>')
            elif k.startswith("c-"):
                fill, stroke, _ = CTYPE[k[2:]]
                self.n.append(f'<rect x="{cx}" y="{cy - 12}" width="30" height="17" rx="3" fill="{fill}" stroke="{stroke}" stroke-width="1.2"/>')
            elif k == "main":
                self.n.append(f'<line x1="{cx}" y1="{cy - 4}" x2="{cx + 30}" y2="{cy - 4}" stroke="{BLUE}" stroke-width="3"/>')
            elif k == "req":
                self.n.append(f'<line x1="{cx}" y1="{cy - 4}" x2="{cx + 30}" y2="{cy - 4}" stroke="{GRAY}" stroke-width="1.8"/>')
            elif k == "aux":
                self.n.append(f'<line x1="{cx}" y1="{cy - 4}" x2="{cx + 30}" y2="{cy - 4}" stroke="{GRAY}" stroke-width="1.8" stroke-dasharray="6 5"/>')
            elif k == "deny":
                self.n.append(f'<line x1="{cx}" y1="{cy - 4}" x2="{cx + 30}" y2="{cy - 4}" stroke="{DENY_C}" stroke-width="2" stroke-dasharray="5 4"/>')
            elif k in ("in", "out"):
                col = IN_C if k == "in" else OUT_C
                self.n.append(f'<rect x="{cx}" y="{cy - 13}" width="30" height="17" rx="8.5" fill="#ffffff" stroke="{col}" stroke-width="1.5"/>')
                self.t(cx + 15, cy, "⇥" if k == "in" else "↦", 12, 700, col, "middle")
            elif k == "mark":
                self.n.append(f'<circle cx="{cx + 15}" cy="{cy - 4}" r="9" fill="#1f1f1f"/>')
                self.t(cx + 15, cy, "1", 11, 700, "#ffffff", "middle")
            self.t(cx + 40, cy + 1, lbl, 13, 400, TXT)
        return h

    def save(self, path, title, subtitle, oy=0):
        # Ek ok uçları (yasak yol) için defs'i genişlet
        super().save(path, title, subtitle, oy)
        s = open(path, encoding="utf-8").read()
        s = s.replace("</defs>", f'<marker id="ad" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto">'
                                 f'<path d="M0,0 L10,5 L0,10 z" fill="{DENY_C}"/></marker></defs>', 1)
        open(path, "w", encoding="utf-8", newline="\n").write(s)
