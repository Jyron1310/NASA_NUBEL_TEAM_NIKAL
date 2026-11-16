"""Genera src/nikal-paleta.css: la paleta narrativa de Nikal aplicada sobre el CSS de Dante.

Recorre fire-map.css y firecal.css, toma solo las declaraciones de color (color, fondos, bordes, sombras,
contornos, fill/stroke) y las vuelve a emitir con el prefijo .nk y los colores decorativos cambiados:
  - neutros y pizarras (grises azulados de Dante)  -> neutros cálidos (papel, tinta, noche);
  - azules, celestes y turquesas de interfaz        -> brasa (acción) o noche (superficies);
  - verde lima y ámbar de Dante                     -> ichu y brasa.
Los colores de datos (rojos, naranjas y amarillos de la escala de calor, sensores, En vivo, niveles) no se
tocan, y tampoco las reglas de leyendas y escalas. Uso: python gen_paleta.py <carpeta src>
"""
import colorsys
import re
import sys
from pathlib import Path

SRC = Path(sys.argv[1])
COLOR_PROPS = re.compile(r"^(--[\w-]+|color|background(-color|-image)?|border(-(top|right|bottom|left))?(-color)?|outline(-color)?|"
                         r"box-shadow|text-shadow|fill|stroke|caret-color|accent-color|text-decoration(-color)?|"
                         r"column-rule(-color)?|scrollbar-color)$")
DATA_SEL = re.compile(r"heat-legend|fw-scale|\.modis|\.viirs|\.outside|fw-risk|is-extrap|anom|legend|fc-dock-points|"
                      r"\.heat\b|\.points\b|\.boundary\b|fa-lv|fa-dot|fa-level|nivel|cal-cell|fc-cal-legend|calidad|"
                      r"is-nodata|live-|liveLayer|fc-live-panel header p i|fw-time-axis|\.red\b|\.orange\b|\.green\b|\.blue\b", re.I)
COLOR = re.compile(r"#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b|rgba?\([^)]*\)")
DANTE_WARM = {"#d97706", "#f59e0b", "#d76a24", "#b26a12", "#f3a62e", "#e7a438", "#fbbf24", "#a54b16", "#ff7659"}


def parse(c):
    c = c.lower()
    if c.startswith("#"):
        h = c[1:]
        if len(h) == 3:
            h = "".join(x * 2 for x in h)
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 1.0, c
    nums = [x.strip() for x in c[c.index("(") + 1:-1].split(",")]
    a = float(nums[3]) if len(nums) > 3 else 1.0
    return int(float(nums[0])), int(float(nums[1])), int(float(nums[2])), a, c


def out(hexc, a):
    if a >= 1:
        return hexc
    r, g, b = (int(hexc[i:i + 2], 16) for i in (1, 3, 5))
    return f"rgba({r},{g},{b},{a:g})"


def band(L, table):
    for lim, val in table:
        if L >= lim:
            return val
    return table[-1][1]


TEXT_N = [(.85, "#f5f3ee"), (.62, "#cdc8bf"), (.45, "#9c968c"), (.3, "#6b655d"), (0, "#141210")]
BG_N = [(.97, "#f5f3ee"), (.9, "#eceae3"), (.8, "#e1ddd3"), (.6, "#c9c3b7"), (.3, "#6b655d"), (.15, "#221e1f"), (0, "#121011")]
LINE_N = [(.85, "#dcd7cc"), (.6, "#c4bdb0"), (.35, "#8a847b"), (0, "#2e2a2b")]


def remap(c, kind, warm_ok):
    r, g, b, a, raw = parse(c)
    h, L, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    hue = h * 360
    if 70 <= hue <= 105 and s > .5 and L > .5:                      # verde lima de Dante -> ichu
        return out("#fca50a", a)
    if kind == "shadow":
        return out("#140e0a", a) if L < .35 else raw
    if warm_ok and raw in DANTE_WARM:                                # ámbar de Dante -> brasa / ichu
        return out("#b83a24" if L < .5 else "#fca50a", a)
    neutral = s < .4 or L > .93 or L < .08
    blue = 160 <= hue <= 260
    if not (neutral or blue):
        return raw                                                    # rojos, naranjas, amarillos: datos
    if neutral:
        if r == g == b == 255 and kind == "text":
            return raw
        return out(band(L, {"text": TEXT_N, "bg": BG_N, "line": LINE_N}[kind]), a)
    # azules / turquesas de interfaz
    if kind == "text":
        return out("#141210" if L < .3 else "#b83a24" if L < .6 else "#fca50a", a)
    if kind == "bg":
        return out("#121011" if L < .25 else "#2a2526" if L < .4 else "#b83a24" if L < .62 else "#f7e9dc", a)
    return out("#2e2a2b" if L < .3 else "#b83a24" if L < .62 else "#efc9b5", a)


def kind_of(prop):
    if prop.startswith("--"):
        return "line" if "line" in prop else "text" if any(k in prop for k in ("muted", "ink", "text")) else "bg"
    if prop in ("color", "caret-color", "fill") or prop.startswith("text-decoration"):
        return "text"
    if prop.startswith(("border", "outline", "stroke", "column-rule")):
        return "line"
    if prop in ("box-shadow", "text-shadow"):
        return "shadow"
    return "bg"


def blocks(css):
    """Devuelve (prelude, body) de primer nivel, respetando llaves anidadas."""
    i, n = 0, len(css)
    while i < n:
        j = css.find("{", i)
        if j < 0:
            return
        depth, k = 1, j + 1
        while depth and k < n:
            depth += {"{": 1, "}": -1}.get(css[k], 0)
            k += 1
        yield css[i:j].strip(), css[j + 1:k - 1]
        i = k


def prefix(sel):
    sel = sel.strip()
    if sel == ":root":
        return ".fw-app.nk"
    if sel in ("html", "body", "#root", "*") or sel.startswith(("html", "body", "#root", "*")):
        return None
    if sel.startswith(".fw-app"):
        return ".fw-app.nk" + sel[len(".fw-app"):]
    return ".nk " + sel


MONO = re.compile(r"(['\"]?(IBM Plex Mono|DM Mono|Cascadia Mono)['\"]?\s*,\s*)?(['\"]?(IBM Plex Mono|DM Mono)['\"]?|var\(--mono\))(\s*,\s*monospace)?|monospace")
SANS = re.compile(r"['\"]?(IBM Plex Sans|Manrope|Inter)['\"]?(\s*,\s*sans-serif)?|sans-serif|system-ui")


def fuente(val):
    val = MONO.sub("var(--nk-mono)", val)
    return SANS.sub("var(--nk-font)", val)


def rule(prelude, body):
    if DATA_SEL.search(prelude):
        return ""
    sels = [p for p in (prefix(s) for s in prelude.split(",")) if p]
    if not sels:
        return ""
    decls = []
    for d in body.split(";"):
        if ":" not in d:
            continue
        prop, val = (x.strip() for x in d.split(":", 1))
        if prop.lower() in ("font", "font-family"):
            decls.append(f"{prop}:{fuente(val)}")
            continue
        if not COLOR_PROPS.match(prop.lower()):
            continue
        k = kind_of(prop.lower())
        warm_ok = True
        new = COLOR.sub(lambda m: remap(m.group(0), k, warm_ok), val)
        decls.append(f"{prop}:{new}")
    return f"{','.join(sels)}{{{';'.join(decls)}}}" if decls else ""


def walk(css):
    res = []
    for prelude, body in blocks(css):
        if prelude.startswith("@media") or prelude.startswith("@supports"):
            inner = "".join(walk(body))
            if inner:
                res.append(f"{prelude}{{{inner}}}")
        elif prelude.startswith("@"):
            continue
        else:
            r = rule(re.sub(r"/\*.*?\*/", "", prelude, flags=re.S).strip(), body)
            if r:
                res.append(r)
    return res


partes = ["/* GENERADO por gen_paleta.py: paleta narrativa de Nikal sobre el CSS de Dante (no editar a mano).\n"
          "   Colores del logo (escala inferno): noche #121011 · papel #f5f3ee · tinta #141210 · brasa #b83a24/#dd513a · ichu #fca50a.\n"
          "   Los colores de datos (calor, sensores, En vivo, niveles, anomalía) quedan igual. */"]
for nombre in ("fire-map.css", "firecal.css"):
    css = re.sub(r"/\*.*?\*/", "", (SRC / nombre).read_text(encoding="utf-8"), flags=re.S)
    reglas = walk(css)
    partes.append(f"/* --- {nombre}: {len(reglas)} reglas --- */")
    partes.extend(reglas)
(SRC / "nikal-paleta.css").write_text("\n".join(partes) + "\n", encoding="utf-8", newline="\n")
print("ok", sum(len(p) for p in partes), "bytes")
