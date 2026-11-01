"""docs/images/detayli-topoloji.png stilinde topoloji diyagramları (dikey akış, tek renk, kesikli zone'lar)."""
from xml.sax.saxutils import escape

FONT = "Segoe UI, Helvetica Neue, Helvetica, Arial, sans-serif"
ZONE_FILL, ZONE_STROKE = "#ededeb", "#c4c4bf"
BOX_FILL, BOX_STROKE = "#f7f7f5", "#c4c4bf"
TXT, SUB = "#1f1f1f", "#5f5f5a"
GRAY, BLUE = "#b3b3ad", "#2f7bd8"
PLANNED = "#9a9a94"

# Güven seviyesine göre zone renkleri: (zemin, kenar, başlık)
PALETTE = {
    "public":   ("#fdecec", "#e3a1a1", "#8c2b2b"),
    "wan":      ("#eef2f7", "#94a3b8", "#334155"),
    "edge":     ("#fff3d9", "#e2b04a", "#7a5200"),
    "dmz":      ("#ffe8d4", "#ec9656", "#8a3d0b"),
    "egress":   ("#ffefe3", "#e39b62", "#7a3b10"),
    "pci":      ("#fde3e3", "#dc6262", "#8b1a1a"),
    "internal": ("#e4eefc", "#6d9fe4", "#1e4b8f"),
    "core":     ("#e7e9fb", "#8790e6", "#2d3a8c"),
    "data":     ("#f0e8fb", "#a383e0", "#4b2a85"),
    "identity": ("#e1f4f1", "#5db5a5", "#145a4f"),
    "mgmt":     ("#e5f4e5", "#6abd6a", "#1f5f1f"),
    "external": ("#f2f2f2", "#a3a3a3", "#333333"),
    "note":     ("#f4f4f2", "#c4c4bf", "#3a3a3a"),
}


class Diagram:
    def __init__(self, w, h):
        self.w, self.h, self.z, self.e, self.n, self.l = w, h, [], [], [], []

    def t(self, x, y, s, size=15.5, weight=400, color=TXT, anchor="start", layer=None):
        (layer if layer is not None else self.n).append(
            f'<text x="{x}" y="{y}" font-family="{FONT}" font-size="{size}" font-weight="{weight}" '
            f'fill="{color}" text-anchor="{anchor}">{escape(s)}</text>')

    def boundary(self, pts, label, color, label_at=None, fill_opacity=0.0):
        """Güven sınırı: çokgen (köşe noktaları), kalın kesikli çizgi + etiket sekmesi"""
        if not hasattr(self, "b"):
            self.b = []
        fill, stroke, tcol = PALETTE[color]
        d = "M " + " L ".join(f"{a},{c}" for a, c in pts) + " Z"
        self.b.append(f'<path d="{d}" fill="{fill}" fill-opacity="{fill_opacity}" stroke="{stroke}" stroke-width="3" stroke-dasharray="14 8"/>')
        lx, ly = label_at if label_at else (pts[0][0] + 14, pts[0][1] - 13)
        w = len(label) * 8.2 + 22
        self.l.append(f'<rect x="{lx}" y="{ly - 4}" width="{w}" height="26" rx="13" fill="{stroke}"/>')
        self.l.append(f'<text x="{lx + 11}" y="{ly + 14}" font-family="{FONT}" font-size="13.5" font-weight="700" fill="#ffffff" letter-spacing="0.6">{escape(label)}</text>')

    def vt(self, x, y, s, size=14, color=SUB, weight=400):
        """Dikey (aşağıdan yukarı) etiket: şeritler boyunca"""
        self.l.append(f'<text x="{x}" y="{y}" font-family="{FONT}" font-size="{size}" font-weight="{weight}" fill="{color}" '
                      f'text-anchor="middle" transform="rotate(-90 {x} {y})">{escape(s)}</text>')

    def channel(self, x, y, w, title, sub, planned=False, h=78):
        dash = ' stroke-dasharray="6 5"' if planned else ""
        self.n.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" fill="#ffffff" stroke="{BOX_STROKE}" stroke-width="1.6"{dash}/>')
        tc = PLANNED if planned else TXT
        if sub:
            self.t(x + w / 2, y + 32, title, 19, 600, tc, "middle")
            self.t(x + w / 2, y + 57, sub, 14.5, 400, PLANNED if planned else SUB, "middle")
        else:
            self.t(x + w / 2, y + h / 2 + 7, title, 19, 600, tc, "middle")

    def zone(self, x, y, w, h, title, lines=(), right=None, planned=False, center=False, title_above=False, color=None):
        op = ' opacity="0.65"' if planned else ""
        fill, stroke, tcol = PALETTE[color] if color else (ZONE_FILL, ZONE_STROKE, TXT)
        self._zfill = fill
        self.z.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" fill="{fill}" stroke="{stroke}" '
                      f'stroke-width="1.8" stroke-dasharray="7 6"{op}/>')
        tc = PLANNED if planned else tcol
        if center:
            self.t(x + w / 2, y + 36, title, 19, 600, tc, "middle", self.z)
            for i, ln in enumerate(lines):
                self.t(x + w / 2, y + 64 + i * 26, ln, 15.5, 400, SUB, "middle", self.z)
        elif title_above:   # başlık okların üstünde, zemin renginde arka planla (oklar altından geçer)
            self.l.append(f'<rect x="{x + 14}" y="{y + 12}" width="{len(title) * 10.6 + 20}" height="34" rx="6" fill="{fill}"/>')
            self.t(x + 24, y + 36, title, 19, 600, tc, layer=self.l)
        else:
            self.t(x + 24, y + 36, title, 19, 600, tc, layer=self.z)
            for i, ln in enumerate(lines):
                self.t(x + 24, y + 66 + i * 26, ln, 15.5, 400, PLANNED if planned else SUB, layer=self.z)
        if right:
            self.t(x + w - 24, y + 36, right, 15, 400, SUB, "end", self.z)

    def box(self, x, y, w, h, title, lines, planned=False, color=None, fill=None):
        dash = ' stroke-dasharray="6 5"' if planned else ""
        stroke = PALETTE[color][1] if color else BOX_STROKE
        self.n.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" fill="{fill or BOX_FILL}" stroke="{stroke}" stroke-width="1.6"{dash}/>')
        self.t(x + 20, y + 34, title, 18, 600, PLANNED if planned else TXT)
        for i, ln in enumerate(lines):
            self.t(x + 20, y + 64 + i * 26, ln, 15.5, 400, PLANNED if planned else "#2b2b2b")

    def ns(self, x, y, w, h, title, lines, planned=False, color=None):
        """Küçük kutu (namespace / bileşen): beyaz zemin, daha küçük yazı"""
        dash = ' stroke-dasharray="6 5"' if planned else ""
        stroke = PALETTE[color][1] if color else BOX_STROKE
        self.n.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="#ffffff" stroke="{stroke}" stroke-width="1.4"{dash}/>')
        self.t(x + 16, y + 28, title, 16, 600, PLANNED if planned else TXT)
        for i, ln in enumerate(lines):
            self.t(x + 16, y + 52 + i * 22, ln, 14, 400, PLANNED if planned else "#2b2b2b")

    def arrow(self, pts, blue=False, dashed=False, label=None, lx=None, ly=None, lanchor="start", lbold=False):
        col = BLUE if blue else GRAY
        w = 3 if blue else 1.6
        dash = ' stroke-dasharray="6 5"' if dashed else ""
        mk = "ab" if blue else "ag"
        d = "M " + " L ".join(f"{a},{b}" for a, b in pts)
        self.e.append(f'<path d="{d}" fill="none" stroke="{col}" stroke-width="{w}"{dash} marker-end="url(#{mk})"/>')
        if label:
            for i, part in enumerate(label.split("\n")):
                self.t(lx, ly + i * 22, part, 15.5, 600 if (lbold or blue) else 400, "#1f1f1f" if blue else SUB, lanchor, self.l)

    def save(self, path, title, subtitle, oy=0):
        defs = ('<defs>'
                f'<marker id="ag" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="9" markerHeight="9" orient="auto"><path d="M0,1 L9,5 L0,9" fill="none" stroke="{GRAY}" stroke-width="1.4"/></marker>'
                f'<marker id="ab" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="{BLUE}"/></marker>'
                '</defs>')
        head = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" viewBox="0 0 {self.w} {self.h}">', defs,
                f'<rect width="{self.w}" height="{self.h}" fill="#ffffff"/>',
                f'<text x="40" y="46" font-family="{FONT}" font-size="25" font-weight="600" fill="{TXT}">{escape(title)}</text>',
                f'<text x="40" y="78" font-family="{FONT}" font-size="16" fill="{SUB}">{escape(subtitle)}</text>']
        body = getattr(self, "b", []) + self.z + self.e + self.n + self.l   # sınırlar en altta
        if oy:   # başlık sabit, içerik aşağı kaydırılır
            body = [f'<g transform="translate(0,{oy})">'] + body + ["</g>"]
        open(path, "w", encoding="utf-8", newline="\n").write("\n".join(head + body + ["</svg>"]))
