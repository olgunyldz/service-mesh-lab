"""Ayrıntı setlerini (prod-detay, demo-detay) doğrudan draw.io bileşenleriyle üretir: resim başına bir sayfa.
SVG'yi çevirmez; aynı resim fonksiyonları (prod_detay.py, demo_detay.py) bu dosyadaki DX sınıfıyla çalışır ve her çizim
çağrısı bir draw.io bileşenine dönüşür:
  namespace, node, pod        -> swimlane container (içindekiler child: birlikte taşınır)
  container, kutu, not        -> yazısı içinde şekil
  güven sınırı, zone, lejant  -> container
  akış oku                    -> başladığı / bittiği şekle bağlı connector
  rozet, numara, etiket       -> şekil
Çalıştırma: python docs/images/src/drawio_detay.py [prod-detay] [demo-detay]   ->  docs/images/<set>/<set>.drawio"""
import html
import os
import re
import sys
from xml.sax.saxutils import quoteattr

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import detay_style
from detay_style import CTYPE, DENY_C, IN_C, OUT_C, D
from topo_style import BLUE, GRAY, PALETTE, PLANNED, SUB, TXT

IMG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
FONT = "fontFamily=Segoe UI;"


def esc(s):
    return html.escape(str(s), quote=False)


def span(s, size, color=None, bold=False):
    st = f"font-size:{size}px;" + (f"color:{color};" if color else "") + ("font-weight:bold;" if bold else "")
    return f'<span style="{st}">{esc(s)}</span>'


class DX(D):
    """detay_style.D ile aynı arayüz; çizim yerine draw.io hücreleri toplar."""

    def __init__(self, w, h):
        super().__init__(w, h)
        self.cells = []   # dict: kind v/e, x y w h, style, value, cont (container mı), text (serbest yazı mı), pts

    # ---- hücre yardımcıları
    def _v(self, x, y, w, h, style, value="", cont=False, text=False):
        self.cells.append(dict(kind="v", x=x, y=y, w=w, h=h, style=style + FONT, value=value, cont=cont, text=text))
        return self.cells[-1]

    def _e(self, pts, style, value=""):
        self.cells.append(dict(kind="e", pts=pts, style=style, value=value))

    def t(self, x, y, s, size=15.5, weight=400, color=TXT, anchor="start", layer=None):
        if not str(s).strip():
            return
        w = len(s) * size * (0.6 if weight >= 600 else 0.55) + 6
        h = size * 1.35
        bx = x if anchor == "start" else (x - w / 2 if anchor == "middle" else x - w)
        align = {"start": "left", "middle": "center", "end": "right"}[anchor]
        self._v(bx, y - size * 1.0, w, h, f"text;html=1;whiteSpace=nowrap;align={align};verticalAlign=middle;spacing=0;fontSize={size:g};"
                f"fontColor={color};fontStyle={1 if weight >= 600 else 0};", esc(s), text=True)

    def text(self, x, y, s, size=14, weight=400, color=TXT, anchor="start"):
        self.t(x, y, s, size, weight, color, anchor)

    def vt(self, x, y, s, size=14, color=SUB, weight=400):
        w = len(s) * size * 0.55 + 6
        h = size * 1.4
        self._v(x - w / 2, y - h / 2 - size * 0.3, w, h, f"text;html=1;whiteSpace=nowrap;align=center;verticalAlign=middle;spacing=0;rotation=-90;"
                f"fontSize={size:g};fontColor={color};fontStyle={1 if weight >= 600 else 0};", esc(s), text=True)

    # ---- sınırlar, zone'lar
    def boundary(self, pts, label, color, label_at=None, fill_opacity=0.0):
        fill, stroke, _ = PALETTE[color]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        self._v(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys),
                f"rounded=0;html=1;container=1;collapsible=0;dropTarget=0;fillColor={fill};fillOpacity={int(fill_opacity * 100)};strokeColor={stroke};"
                f"strokeWidth=3;dashed=1;dashPattern=4 2;verticalAlign=top;align=left;spacingLeft=14;spacingTop=-13;fontSize=13.5;fontStyle=1;"
                f"fontColor=#ffffff;labelBackgroundColor={stroke};", esc(label), cont=True)

    def firewall(self, x, y, w, h, text, tx=None):
        self._v(x, y, w, h, f"rounded=1;html=1;fillColor=#fbe9e4;strokeColor=#c4634a;strokeWidth=1.4;align=left;verticalAlign=middle;"
                f"spacingLeft={(tx - x) if tx is not None else 14};fontSize=13.5;fontStyle=1;fontColor=#8a2f1c;", esc(text))

    def zone(self, x, y, w, h, title, lines=(), right=None, planned=False, center=False, title_above=False, color=None):
        fill, stroke, tcol = PALETTE[color] if color else ("#ededeb", "#c4c4bf", TXT)
        tc = PLANNED if planned else tcol
        val = f'<span style="font-size:19px;color:{tc};">{esc(title)}</span>'
        if lines:
            val += "<br>" + "<br>".join(span(ln, 15.5, PLANNED if planned else SUB) for ln in lines)
        self._v(x, y, w, h, f"rounded=1;arcSize=3;html=1;container=1;collapsible=0;dropTarget=0;whiteSpace=wrap;fillColor={fill};strokeColor={stroke};"
                f"strokeWidth=1.8;dashed=1;dashPattern=4 3;{'opacity=65;' if planned else ''}verticalAlign=top;"
                f"align={'center' if center else 'left'};spacingLeft=24;spacingTop=12;spacingRight=12;", val, cont=True)
        if right:
            self.t(x + w - 24, y + 36, right, 15, 400, SUB, "end")

    def channel(self, x, y, w, title, sub, planned=False, h=78):
        tc = PLANNED if planned else TXT
        val = f'<span style="font-size:19px;color:{tc};font-weight:600;">{esc(title)}</span>'
        if sub:
            val += "<br>" + span(sub, 14.5, PLANNED if planned else SUB)
        self._v(x, y, w, h, f"rounded=1;arcSize=15;html=1;whiteSpace=wrap;fillColor=#ffffff;strokeColor=#c4c4bf;strokeWidth=1.6;"
                f"{'dashed=1;' if planned else ''}align=center;verticalAlign=middle;", val)

    # ---- namespace, node, pod, container
    def nsbox(self, x, y, w, h, title, color, sub=None):
        fill, stroke, tcol = PALETTE[color]
        self._v(x, y, w, h, f"swimlane;html=1;startSize=28;rounded=1;arcSize=4;container=1;collapsible=0;fillColor={fill};swimlaneFillColor=#ffffff;"
                f"strokeColor={stroke};strokeWidth=1.5;dashed=1;dashPattern=4 3;swimlaneLine=0;align=left;spacingLeft=12;fontSize=14;fontStyle=1;"
                f"fontColor={tcol};", esc("ns " + title), cont=True)
        if sub:
            self.t(x + w - 10, y + 19, sub, 12, 400, SUB, "end")

    def node(self, x, y, w, h, title, sub=None):
        self._v(x, y, w, h, "swimlane;html=1;startSize=26;rounded=1;arcSize=2;container=1;collapsible=0;fillColor=#55554f;swimlaneFillColor=#fbfbfa;"
                "strokeColor=#55554f;strokeWidth=2;swimlaneLine=0;align=left;spacingLeft=10;fontSize=13.5;fontStyle=1;fontColor=#ffffff;",
                esc("▣ " + title), cont=True)
        if sub:   # başlık şeridi koyu: açık renk
            self.t(x + w - 10, y + 18, sub, 12, 400, "#e4e4de", "end")

    def pod(self, x, y, w, h, name, kind, color, containers=(), agent=False):
        stroke = PALETTE[color][1]
        if h is None:
            h = 34 + sum(22 + 17 * len(c[2] if len(c) > 2 else ()) + 5 for c in containers)
        self._v(x, y, w, h, f"swimlane;html=1;startSize=26;rounded=1;arcSize=6;container=1;collapsible=0;fillColor=#ffffff;swimlaneFillColor=#ffffff;"
                f"strokeColor={stroke};strokeWidth=1.8;{'dashed=1;dashPattern=4 3;' if agent else ''}swimlaneLine=0;align=left;spacingLeft=8;"
                f"fontSize=13.5;fontStyle=1;fontColor={TXT};", esc(("⬡ " if agent else "◼ ") + name), cont=True)
        if kind:
            self.t(x + w - 8, y + 19, kind, 11.5, 400, SUB, "end")
        cy = y + 28
        for c in containers:
            lines = c[2] if len(c) > 2 else ()
            ch = 22 + 17 * len(lines)
            self.container(x + 8, cy, w - 16, ch, c[0], c[1], lines)
            cy += ch + 5
        return y + h

    def container(self, x, y, w, h, name, ctype, lines=()):
        fill, stroke, _ = CTYPE[ctype]
        val = span(name, 12.5, TXT, True)
        if lines:
            val += "<br>" + "<br>".join(span(ln, 11.5, "#3a3a3a") for ln in lines)
        self._v(x, y, w, h, f"rounded=1;arcSize=8;html=1;whiteSpace=wrap;fillColor={fill};strokeColor={stroke};strokeWidth=1.2;"
                f"{'dashed=1;' if ctype == 'init' else ''}align=left;verticalAlign=top;spacingLeft=8;spacingTop=0;spacing=2;", val)

    def box(self, x, y, w, h, title, lines=(), color=None, fill="#ffffff", size=13):
        stroke = PALETTE[color][1] if color else "#c4c4bf"
        val = span(title, size + 1, TXT, True)
        if lines:
            val += "<br>" + "<br>".join(span(ln, size - 1, "#2b2b2b") for ln in lines)
        self._v(x, y, w, h, f"rounded=1;arcSize=6;html=1;whiteSpace=wrap;fillColor={fill};strokeColor={stroke};strokeWidth=1.6;"
                f"align=left;verticalAlign=top;spacingLeft=10;spacingTop=4;", val)

    def note(self, x, y, w, title, lines, size=13):
        h = 34 + len(lines) * (size + 6)
        val = span(title, size + 1, TXT, True) + "<br>" + "<br>".join(span(ln, size, "#2b2b2b") for ln in lines)
        self._v(x, y, w, h, "rounded=1;arcSize=4;html=1;whiteSpace=wrap;fillColor=#fffdf3;strokeColor=#d8cfa3;strokeWidth=1.3;"
                "align=left;verticalAlign=top;spacingLeft=12;spacingTop=6;", val)
        return h

    # ---- rozet, numara, etiket
    def badge(self, x, y, text, kind="in", anchor="start"):
        col = {"in": IN_C, "out": OUT_C, "deny": DENY_C}[kind]
        s = {"in": "⇥ ", "out": "↦ ", "deny": "✕ "}[kind] + text
        w = len(s) * 6.9 + 16
        bx = x if anchor == "start" else x - w
        self._v(bx, y - 13, w, 19, f"rounded=1;arcSize=50;html=1;whiteSpace=nowrap;fillColor=#ffffff;strokeColor={col};strokeWidth=1.5;"
                f"align=left;verticalAlign=middle;spacingLeft=8;fontSize=11.5;fontStyle=1;fontColor={col};", esc(s))
        return w

    def marker(self, x, y, n, color="#1f1f1f"):
        self._v(x - 13, y - 13, 26, 26, f"ellipse;html=1;fillColor={color};strokeColor=none;fontColor=#ffffff;fontSize=13;fontStyle=1;"
                "align=center;verticalAlign=middle;", esc(n))

    def link(self, x, y, label):
        w = len(label) * 7.2 + 18
        self._v(x, y - 14, w, 21, "rounded=1;arcSize=50;html=1;fillColor=#1f1f1f;strokeColor=none;fontColor=#ffffff;fontSize=12.5;fontStyle=1;"
                "align=center;verticalAlign=middle;", esc(label))

    # ---- oklar
    def flow(self, pts, kind="main", label=None, lx=None, ly=None, anchor="start"):
        if kind == "deny":
            self._e(pts, f"endArrow=block;endFill=1;strokeColor={DENY_C};strokeWidth=2;dashed=1;dashPattern=5 4;")
            if label:
                self.t(lx, ly, label, 12.5, 600, DENY_C, anchor)
            return
        self.arrow(pts, blue=(kind == "main"), dashed=(kind == "aux"))
        if label:
            for i, part in enumerate(label.split("\n")):
                self.t(lx, ly + i * 17, part, 12.5, 600 if kind == "main" else 400, "#1f1f1f" if kind == "main" else SUB, anchor)

    def arrow(self, pts, blue=False, dashed=False, label=None, lx=None, ly=None, lanchor="start", lbold=False):
        if blue:
            st = f"endArrow=block;endFill=1;strokeColor={BLUE};strokeWidth=3;"
        else:
            st = f"endArrow=open;endFill=0;strokeColor={GRAY};strokeWidth=1.6;"
        self._e(pts, st + ("dashed=1;dashPattern=6 5;" if dashed else ""))
        if label:
            for i, part in enumerate(label.split("\n")):
                self.t(lx, ly + i * 22, part, 15.5, 600 if (lbold or blue) else 400, "#1f1f1f" if blue else SUB, lanchor)

    # ---- lejant
    def legend(self, x, y, w, zones=(), extra=True, cols=4):
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
        self._v(x, y, w, h, "rounded=1;arcSize=3;html=1;container=1;collapsible=0;fillColor=#fafaf8;strokeColor=#c4c4bf;strokeWidth=1.2;"
                "align=left;verticalAlign=top;spacingLeft=14;spacingTop=8;fontSize=15;fontStyle=1;", "Lejant", cont=True)
        cw = (w - 28) / cols
        for i, (k, z, lbl) in enumerate(items):
            cx = x + 14 + (i % cols) * cw
            cy = y + 46 + (i // cols) * 28
            sw = "html=1;"
            if k == "zone":
                fill, stroke, _ = PALETTE[z]
                self._v(cx, cy - 12, 30, 17, sw + f"rounded=1;fillColor={fill};strokeColor={stroke};strokeWidth=1.5;")
            elif k == "bound":
                self._e([(cx, cy - 4), (cx + 30, cy - 4)], "endArrow=none;strokeColor=#6d9fe4;strokeWidth=3;dashed=1;dashPattern=3 2;")
            elif k == "ns":
                self._v(cx, cy - 12, 30, 17, sw + "rounded=1;fillColor=#ffffff;strokeColor=#6d9fe4;strokeWidth=1.4;dashed=1;")
            elif k == "node":
                self._v(cx, cy - 12, 30, 17, sw + "rounded=1;fillColor=#fbfbfa;strokeColor=#55554f;strokeWidth=2;")
            elif k in ("pod", "agentpod"):
                self._v(cx, cy - 12, 30, 17, sw + f"rounded=1;fillColor=#ffffff;strokeColor=#6d9fe4;strokeWidth=1.8;{'dashed=1;' if k == 'agentpod' else ''}")
            elif k.startswith("c-"):
                fill, stroke, _ = CTYPE[k[2:]]
                self._v(cx, cy - 12, 30, 17, sw + f"rounded=1;fillColor={fill};strokeColor={stroke};strokeWidth=1.2;")
            elif k in ("main", "req", "aux", "deny"):
                st = {"main": f"strokeColor={BLUE};strokeWidth=3;", "req": f"strokeColor={GRAY};strokeWidth=1.8;",
                      "aux": f"strokeColor={GRAY};strokeWidth=1.8;dashed=1;", "deny": f"strokeColor={DENY_C};strokeWidth=2;dashed=1;"}[k]
                self._e([(cx, cy - 4), (cx + 30, cy - 4)], "endArrow=none;" + st)
            elif k in ("in", "out"):
                col = IN_C if k == "in" else OUT_C
                self._v(cx, cy - 13, 30, 17, sw + f"rounded=1;arcSize=50;fillColor=#ffffff;strokeColor={col};strokeWidth=1.5;fontColor={col};"
                        "fontSize=12;fontStyle=1;", "⇥" if k == "in" else "↦")
            elif k == "mark":
                self._v(cx + 6, cy - 13, 18, 18, sw + "ellipse;fillColor=#1f1f1f;strokeColor=none;fontColor=#ffffff;fontSize=11;fontStyle=1;", "1")
            self.t(cx + 40, cy + 1, lbl, 13, 400, TXT)
        return h

    # ---- kaydet: sayfayı topla
    def save(self, path, title, subtitle, oy=0):
        # Doğrudan eklenmiş SVG öğeleri (tablo satırları, kulvar çizgileri): rect -> şekil, line -> çizgi
        for raw in self.z + self.e + self.n + self.l:
            m = re.match(r'<rect x="([-\d.]+)" y="([-\d.]+)" width="([-\d.]+)" height="([-\d.]+)"[^>]*?fill="([^"]+)" stroke="([^"]+)" stroke-width="([\d.]+)"', raw)
            if m:
                x, y, w, h, fill, stroke, sw = m.groups()
                self.cells.insert(0, dict(kind="v", x=float(x), y=float(y), w=float(w), h=float(h), cont=False, text=False, value="",
                                          style=f"rounded=1;arcSize=8;html=1;fillColor={fill};strokeColor={stroke};strokeWidth={sw};" + FONT))
                continue
            m = re.match(r'<line x1="([-\d.]+)" y1="([-\d.]+)" x2="([-\d.]+)" y2="([-\d.]+)" stroke="([^"]+)" stroke-width="([\d.]+)"(.*)', raw)
            if m:
                x1, y1, x2, y2, stroke, sw, rest = m.groups()
                self.cells.insert(0, dict(kind="e", pts=[(float(x1), float(y1)), (float(x2), float(y2))],
                                          style=f"endArrow=none;strokeColor={stroke};strokeWidth={sw};" + ("dashed=1;" if "dasharray" in rest else "")))
        for c in self.cells:   # başlık sabit, içerik aşağı kaydırılır
            if c["kind"] == "v":
                c["y"] += oy
            else:
                c["pts"] = [(a, b + oy) for a, b in c["pts"]]
        self.t(40, 46, title, 25, 600, TXT)
        self.t(40, 78, subtitle, 16, 400, SUB)
        PAGES.append((title.split(":")[0].strip(), self.w, self.h, page_xml(self.cells)))


def page_xml(cells):
    verts = [c for c in cells if c["kind"] == "v"]
    conts = [c for c in verts if c["cont"]]
    for i, c in enumerate(verts):
        c["id"] = f"v{i + 2}"
        c["area"] = c["w"] * c["h"]

    def inside(px, py, c, pad=0):
        return c["x"] - pad <= px <= c["x"] + c["w"] + pad and c["y"] - pad <= py <= c["y"] + c["h"] + pad

    # ebeveyn: merkezini içeren, kendisinden büyük en küçük container
    for c in verts:
        cx, cy = c["x"] + c["w"] / 2, c["y"] + c["h"] / 2
        cand = [p for p in conts if p is not c and p["area"] > c["area"] and inside(cx, cy, p)]
        c["parent"] = min(cand, key=lambda p: p["area"]) if cand else None

    # derinlik: ebeveyn önce yazılsın
    def depth(c):
        n, p = 0, c["parent"]
        while p:
            n, p = n + 1, p["parent"]
        return n

    out = []
    for c in sorted(verts, key=depth):
        p = c["parent"]
        px, py = (p["x"], p["y"]) if p else (0, 0)
        out.append(f'<mxCell id="{c["id"]}" value={quoteattr(c["value"])} style={quoteattr(c["style"])} vertex="1" parent="{p["id"] if p else "1"}">'
                   f'<mxGeometry x="{c["x"] - px:.1f}" y="{c["y"] - py:.1f}" width="{c["w"]:.1f}" height="{c["h"]:.1f}" as="geometry"/></mxCell>')

    shapes = [c for c in verts if not c["text"]]

    def attach(pt):
        """Noktaya kenarı en yakın (±8 px) şekil: oku ona bağla; yoksa serbest uç."""
        px, py = pt
        best = None
        for c in shapes:
            if not inside(px, py, c, 8):
                continue
            d = min(abs(px - c["x"]), abs(px - c["x"] - c["w"]), abs(py - c["y"]), abs(py - c["y"] - c["h"]))
            if d <= 8 and (best is None or c["area"] < best["area"]):
                best = c
        return best

    for i, e in enumerate(c for c in cells if c["kind"] == "e"):
        pts = e["pts"]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        cand = [p for p in conts if all(inside(a, b, p) for a, b in pts)]
        par = min(cand, key=lambda p: p["area"]) if cand else None
        ox, oy = (par["x"], par["y"]) if par else (0, 0)
        st = "html=1;rounded=0;edgeStyle=none;" + e["style"]
        src, tgt = attach(pts[0]), attach(pts[-1])
        attrs = ""
        if src and len(pts) > 1 and src is not tgt:
            st += f"exitX={(pts[0][0] - src['x']) / src['w']:.3f};exitY={(pts[0][1] - src['y']) / src['h']:.3f};exitDx=0;exitDy=0;exitPerimeter=0;"
            attrs += f' source="{src["id"]}"'
        if tgt and len(pts) > 1 and src is not tgt:
            st += f"entryX={(pts[-1][0] - tgt['x']) / tgt['w']:.3f};entryY={(pts[-1][1] - tgt['y']) / tgt['h']:.3f};entryDx=0;entryDy=0;entryPerimeter=0;"
            attrs += f' target="{tgt["id"]}"'
        mids = "".join(f'<mxPoint x="{a - ox:.1f}" y="{b - oy:.1f}"/>' for a, b in pts[1:-1])
        arr = f'<Array as="points">{mids}</Array>' if mids else ""
        out.append(f'<mxCell id="e{i + 1}" value="" style={quoteattr(st)} edge="1" parent="{par["id"] if par else "1"}"{attrs}>'
                   f'<mxGeometry relative="1" as="geometry"><mxPoint x="{pts[0][0] - ox:.1f}" y="{pts[0][1] - oy:.1f}" as="sourcePoint"/>'
                   f'<mxPoint x="{pts[-1][0] - ox:.1f}" y="{pts[-1][1] - oy:.1f}" as="targetPoint"/>{arr}</mxGeometry></mxCell>')
    return "".join(out)


PAGES = []


def build(name):
    """name: prod-detay | demo-detay -> ilgili üretecin resimlerini draw.io sayfalarına çevir."""
    mod = __import__({"prod-detay": "prod_detay", "demo-detay": "demo_detay"}[name])
    mod.D = DX
    PAGES.clear()
    for k in sorted(mod.IMAGES):
        mod.IMAGES[k]()
    pages = []
    for i, (title, w, h, body) in enumerate(PAGES):
        pages.append(f'<diagram id="p{i:02d}" name={quoteattr(title)}>'
                     f'<mxGraphModel dx="{w}" dy="{h}" grid="0" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" '
                     f'pageScale="1" pageWidth="{w}" pageHeight="{h}" background="#ffffff" math="0" shadow="0">'
                     f'<root><mxCell id="0"/><mxCell id="1" parent="0"/>{body}</root></mxGraphModel></diagram>')
    path = os.path.join(IMG, name, f"{name}.drawio")
    open(path, "w", encoding="utf-8", newline="\n").write(
        f'<mxfile host="app.diagrams.net" agent="service-mesh-lab drawio_detay" version="24.0.0">{"".join(pages)}</mxfile>')
    print("ok", os.path.normpath(path), f"({len(pages)} sayfa)")


if __name__ == "__main__":
    for n in sys.argv[1:] or ["prod-detay", "demo-detay"]:
        build(n)
