#!/usr/bin/env python3
"""Render the profile README cards as animated SVGs into cards/.

    python scripts/build_cards.py            # animated cards  -> cards/
    STATIC=1 python scripts/build_cards.py   # final frame only -> preview/ (+ preview/index.html)

Designed for <img> embedding (GitHub camo): no scripts, no external refs, no foreignObject.
Animation = CSS keyframes in an inline <style> + SMIL. Every animation is off under
prefers-reduced-motion (SMIL groups swap to static twins). Fonts are subset per card with
pyftsubset and embedded as base64 WOFF2 data URIs.
"""
import base64, datetime as dt, json, os, subprocess, sys, tempfile
from collections import defaultdict
from pathlib import Path
from xml.sax.saxutils import escape

from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parent.parent
CFG = json.loads((ROOT / "scripts/config.json").read_text(encoding="utf-8"))
DATA = json.loads((ROOT / "data/contributions.json").read_text(encoding="utf-8"))
STATIC = os.environ.get("STATIC", "").lower() not in ("", "0", "false", "no")
OUT = ROOT / ("preview" if STATIC else "cards")

# ---- brand tokens (from the portfolio's dark theme) -------------------------------------
BG, SURFACE, ELEV = "#000000", "#000000", "#171717"
BORDER, TEXT, TEXT2, MUTED = "#262626", "#fafafa", "#a1a1aa", "#71717a"
INDIGO, INDIGO_HI, CYAN, EMERALD = "#6366f1", "#818cf8", "#22d3ee", "#34d399"
W = 800

FONTS = {  # key -> (family, weight, file)
    "i400": ("Inter", 400, "inter-latin-400-normal.woff2"),
    "i600": ("Inter", 600, "inter-latin-600-normal.woff2"),
    "i800": ("Inter", 800, "inter-latin-800-normal.woff2"),
    "m500": ("JetBrains Mono", 500, "jetbrains-mono-latin-500-normal.woff2"),
    "m700": ("JetBrains Mono", 700, "jetbrains-mono-latin-700-normal.woff2"),
}
STACK = {"Inter": "Inter,-apple-system,'Segoe UI',Roboto,sans-serif",
         "JetBrains Mono": "'JetBrains Mono',ui-monospace,Menlo,Consolas,monospace"}
_ttf = {}

def _font(key):
    if key not in _ttf:
        f = TTFont(ROOT / "scripts/fonts" / FONTS[key][2])
        _ttf[key] = (f.getBestCmap(), f["hmtx"], f["head"].unitsPerEm)
    return _ttf[key]

def tw(text, key, size, spacing=0.0):
    cmap, hmtx, upm = _font(key)
    return sum(hmtx[cmap[ord(c)]][0] if ord(c) in cmap else upm * .6 for c in text) * size / upm + spacing * len(text)

def wrap(text, key, size, maxw, maxlines=3):
    lines, cur = [], ""
    for word in text.split():
        t = (cur + " " + word).strip()
        if tw(t, key, size) <= maxw or not cur:
            cur = t
        else:
            lines.append(cur); cur = word
    lines.append(cur)
    if len(lines) > maxlines:
        lines = lines[:maxlines]; lines[-1] = lines[-1].rstrip(".,") + "…"
    return lines

def mix(fg, bg, a):
    f = [int(fg[i:i + 2], 16) for i in (1, 3, 5)]; b = [int(bg[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(round(x * a + y * (1 - a)) for x, y in zip(f, b))

KEYFRAMES = """
@keyframes fu{from{opacity:0;transform:translateY(10px)}}
@keyframes fi{from{opacity:0}}
@keyframes gr{from{transform:scaleY(0)}}
@keyframes sx{from{transform:scaleX(0)}}
@keyframes pp{from{opacity:0;transform:scale(.4)}}
@keyframes rg{from{stroke-dasharray:0 100}}
@keyframes dr{50%{transform:translate(26px,-12px)}}
.fu{animation:fu .7s cubic-bezier(.2,.7,.2,1) both}
.fi{animation:fi .6s ease-out both}
.gr{transform-box:fill-box;transform-origin:50% 100%;animation:gr .8s cubic-bezier(.2,.7,.2,1) both}
.sx{transform-box:fill-box;transform-origin:0 50%;animation:sx .7s cubic-bezier(.2,.7,.2,1) both}
.pp{transform-box:fill-box;transform-origin:center;animation:pp .35s ease-out both}
.rg{animation:rg 1.1s cubic-bezier(.2,.7,.2,1) both}
.dr{animation:dr 16s ease-in-out infinite}
.still{display:none}
@media (prefers-reduced-motion:reduce){*{animation:none!important}.motion{display:none}.still{display:inline}}
"""

class Card:
    def __init__(s, name, w, h, label, delay=0.0):
        s.name, s.w, s.h, s.label, s.d0 = name, w, h, label, delay
        s.body, s.defs, s.chars = [], [], defaultdict(set)

    def a(s, cls, delay=0.0):  # animation attributes (none in STATIC)
        return "" if STATIC else f' class="{cls}" style="animation-delay:{s.d0 + delay:.2f}s"'

    def add(s, x): s.body.append(x)

    def text(s, x, y, t, key, size, fill, anchor="start", cls="fu", delay=0.0, ls=0.0):
        s.chars[key].update(t)
        fam, wt, _ = FONTS[key]
        lsa = f' letter-spacing="{ls}"' if ls else ""
        s.add(f'<text x="{x}" y="{y}" font-family="{STACK[fam]}" font-weight="{wt}" font-size="{size}" '
              f'fill="{fill}" text-anchor="{anchor}"{lsa}{s.a(cls, delay) if cls else ""}>{escape(t)}</text>')

    def smil(s, motion, still):
        s.add(still if STATIC else f'<g class="motion">{motion}</g><g class="still">{still}</g>')

    def frame(s, rx=10):
        s.defs.append(f'<clipPath id="cp"><rect width="{s.w}" height="{s.h}" rx="{rx}"/></clipPath>')
        s.body.insert(0, f'<rect width="{s.w}" height="{s.h}" rx="{rx}" fill="{SURFACE}"/>')
        s.add(f'<rect x=".5" y=".5" width="{s.w - 1}" height="{s.h - 1}" rx="{rx}" fill="none" stroke="{BORDER}"/>')

    def fontcss(s):
        css = []
        with tempfile.TemporaryDirectory() as td:
            for key, chars in s.chars.items():
                fam, wt, fn = FONTS[key]
                cmap = _font(key)[0]
                miss = [c for c in chars if ord(c) not in cmap and not c.isspace()]
                if miss: print(f"  warn {s.name}: no glyph for {miss} in {fn}", file=sys.stderr)
                out = Path(td) / f"{key}.woff2"
                subprocess.run(["pyftsubset", str(ROOT / "scripts/fonts" / fn), f"--text={''.join(sorted(chars))}",
                                "--flavor=woff2", f"--output-file={out}", "--layout-features=kern",
                                "--no-hinting", "--desubroutinize"], check=True)
                b64 = base64.b64encode(out.read_bytes()).decode()
                css.append(f"@font-face{{font-family:'{fam}';font-weight:{wt};font-style:normal;"
                           f"src:url(data:font/woff2;base64,{b64}) format('woff2')}}")
        return "".join(css)

    def render(s):
        style = s.fontcss() + ("" if STATIC else KEYFRAMES)
        desc = escape(s.label)
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{s.w}" height="{s.h}" viewBox="0 0 {s.w} {s.h}" '
               f'role="img" aria-label="{desc}"><title>{desc}</title><style>{style}</style>'
               f'<defs>{"".join(s.defs)}</defs>{"".join(s.body)}</svg>\n')
        OUT.mkdir(exist_ok=True)
        (OUT / f"{s.name}.svg").write_text(svg, encoding="utf-8")
        print(f"  {s.name}.svg  {len(svg) / 1024:.1f} KB")
        return s.name

GRAD = f'<linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{INDIGO}"/><stop offset="1" stop-color="{CYAN}"/></linearGradient>'
GRADV = f'<linearGradient id="gv" x1="0" y1="1" x2="0" y2="0"><stop offset="0" stop-color="{INDIGO}"/><stop offset="1" stop-color="{CYAN}"/></linearGradient>'

# ---- data ---------------------------------------------------------------------------------
days = sorted(((dt.date.fromisoformat(d["date"]), d["count"]) for d in DATA["days"]))
today = days[-1][0]
by_date = dict(days)
total = sum(c for _, c in days)
active = sum(1 for _, c in days if c)
busiest = max(days, key=lambda x: x[1])
longest = run = 0
for _, c in days:
    run = run + 1 if c else 0; longest = max(longest, run)
cur, d = 0, today
if not by_date.get(d): d -= dt.timedelta(days=1)  # today may still be empty
while by_date.get(d): cur += 1; d -= dt.timedelta(days=1)
months = []  # last 12 calendar months ending with the current one
y, m = today.year, today.month
for i in range(11, -1, -1):
    mm = m - i; yy = y + (mm - 1) // 12; mm = (mm - 1) % 12 + 1
    months.append((yy, mm, sum(c for dd, c in days if dd.year == yy and dd.month == mm)))
SAMPLE_NOTE = "  ·  sample data" if DATA.get("sample") else ""
MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# ---- 1. hero ------------------------------------------------------------------------------
def hero():
    c = Card("hero", W, 270, f"{CFG['name']}. {CFG['hero_line']} {CFG['status']}.")
    c.frame()
    pill = CFG["status"]
    dot = lambda r: f'<circle cx="52" cy="52" r="{r}" fill="{EMERALD}"/>'
    ring = f'<circle cx="52" cy="52" r="3.5" fill="none" stroke="{EMERALD}"><animate attributeName="r" values="3.5;10" dur="2.4s" begin="{c.d0 + .6}s" repeatCount="indefinite"/><animate attributeName="opacity" values=".8;0" dur="2.4s" begin="{c.d0 + .6}s" repeatCount="indefinite"/></circle>'
    c.smil(dot(3.5) + ring, dot(3.5))
    c.text(66, 56, pill, "m500", 12, TEXT2, delay=0.2)
    c.text(48, 128, CFG["name"], "i600", 52, TEXT, delay=0.3, ls=-1.2)
    c.add(f'<rect x="48" y="146" width="40" height="2" fill="{INDIGO}"{c.a("sx", 0.6)}/>')
    c.text(48, 182, CFG["role"].replace("  ·  ", " · "), "m500", 13, INDIGO_HI, delay=0.7)
    por = CFG["portrait"]; use_por = por["enabled"] and (ROOT / por["path"]).exists()
    maxw = 520 if use_por else W - 96
    for i, ln in enumerate(wrap(CFG["hero_line"], "i400", 16, maxw, 2)):
        c.text(48, 216 + i * 25, ln, "i400", 16, TEXT2, delay=0.9 + i * .1)
    if use_por:
        b64 = base64.b64encode((ROOT / por["path"]).read_bytes()).decode()
        c.defs.append('<clipPath id="pc"><circle cx="656" cy="135" r="80"/></clipPath>')
        c.add(f'<g{c.a("fu", 0.5)}><circle cx="656" cy="135" r="81" fill="none" stroke="{BORDER}" stroke-width="2"/>'
              f'<image href="data:image/jpeg;base64,{b64}" x="576" y="55" width="160" height="160" clip-path="url(#pc)" preserveAspectRatio="xMidYMid slice"/></g>')
    return c.render()

# ---- 2. tiles -----------------------------------------------------------------------------
def tile(i, t, letter=None):
    c = Card(f"tile-{t['title'].lower().replace('é', 'e')}", 260, 84, f"{t['title']}: {t['sub']}", delay=0.9 + i * 0.12)
    c.frame()
    c.text(24, 38, t["title"], "i600", 17, TEXT, delay=0)
    c.text(24, 59, t["sub"], "m500", 11, MUTED, delay=0.06)
    arrow = lambda: f'<path d="M-5 5L5 -5M-3 -5H5V3" fill="none" stroke="{TEXT2}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>'
    mot = f'<g transform="translate(230 40)"><g>{arrow()}<animateTransform attributeName="transform" type="translate" values="0 0;2 -2;0 0" dur="2.6s" begin="{c.d0 + 1}s" repeatCount="indefinite"/></g></g>'
    c.smil(mot, f'<g transform="translate(230 40)">{arrow()}</g>')
    return c.render()

# ---- 3. monthly chart + stats -------------------------------------------------------------
def activity():
    c = Card("activity", W, 372, f"Contributions per month over the last 12 months, {total} in total. Current streak {cur} days, "
             f"{active} active days, busiest day {busiest[0]:%b %d, %Y} with {busiest[1]} contributions.", delay=1.6)
    c.frame()
    c.text(40, 52, "Contributions per month", "i600", 18, TEXT)
    c.text(40, 74, f"{total} in the last 12 months{SAMPLE_NOTE}", "m500", 12, MUTED, delay=0.05)
    x0, slot, base, top = 40, 60, 262, 122
    mx = max(1, max(v for *_, v in months)); bw = 34
    for k in range(4):
        gy = base - (base - top) * k / 3
        c.add(f'<line x1="40" x2="760" y1="{gy:.0f}" y2="{gy:.0f}" stroke="{BORDER}" />')
    peak = max(range(12), key=lambda i: months[i][2])
    for i, (yy, mm, v) in enumerate(months):
        x = x0 + i * slot + (slot - bw) / 2; h = max(3, (base - top) * v / mx); dl = 0.15 + i * 0.06
        c.add(f'<rect x="{x:.0f}" y="{base - h:.1f}" width="{bw}" height="{h:.1f}" rx="3" fill="{INDIGO}" opacity="{1 if i == peak else .5}"{c.a("gr", dl)}/>')
        c.text(x + bw / 2, base - h - 8, str(v), "m700" if i == peak else "m500", 11, TEXT if i == peak else TEXT2, anchor="middle", delay=dl + .35)
        c.text(x + bw / 2, base + 20, MON[mm - 1], "m500", 11, MUTED, anchor="middle", delay=dl)
    stats = [(f"{cur} day{'s' if cur != 1 else ''}", f"Current streak, longest {longest}"),
             (f"{active} days", f"Active, {active * 100 // len(days)}% of the year"),
             (f"{busiest[1]} contributions", f"Busiest day, {MON[busiest[0].month - 1]} {busiest[0].day}, {busiest[0].year}")]
    for i, (big, small) in enumerate(stats):
        x = 40 + i * 240 + (i and 12)
        if i: c.add(f'<line x1="{x - 16}" x2="{x - 16}" y1="302" y2="346" stroke="{BORDER}"/>')
        c.text(x, 326, big, "i600", 24, TEXT, delay=1.0 + i * .12)
        c.text(x, 346, small, "i400", 12, TEXT2, delay=1.05 + i * .12)
    return c.render()

# ---- 3b. stats + languages, streak --------------------------------------------------------
def _range(a, b):
    f = lambda d: f"{MON[d.month - 1]} {d.day}"
    return f"{f(a)} to {f(b)}" if a != b else f(a)

def stats():
    st, langs = DATA["stats"], DATA.get("languages", [])
    c = Card("stats", W, 250, f"GitHub stats: {st['stars']} stars, {st['commits']} commits in the last 12 months, {st['prs']} pull requests, "
             f"{st['issues']} issues. Most used languages: " + ", ".join(l["name"] for l in langs[:6]) + ".", delay=1.2)
    c.frame()
    c.text(40, 52, "GitHub stats", "i600", 18, TEXT)
    rows = [("Stars earned", st["stars"]), ("Commits, last 12 months", st["commits"]), ("Pull requests", st["prs"]),
            ("Issues opened", st["issues"]), ("Repositories contributed to", st["contributed_to"])]
    for i, (lab, val) in enumerate(rows):
        y = 94 + i * 30
        c.text(40, y, lab, "i400", 14, TEXT2, delay=0.1 + i * .07)
        c.text(380, y, f"{val:,}", "m700", 14, TEXT, anchor="end", delay=0.15 + i * .07)
        if i < len(rows) - 1: c.add(f'<line x1="40" x2="380" y1="{y + 12}" y2="{y + 12}" stroke="{BORDER}"/>')
    c.add(f'<line x1="420" x2="420" y1="40" y2="212" stroke="{BORDER}"/>')
    c.text(460, 52, "Most used languages", "i600", 18, TEXT, delay=.1)
    top = langs[:6]; tot = sum(l["bytes"] for l in top) or 1
    x, bw = 460, 300
    c.add(f'<clipPath id="lb"><rect x="{x}" y="72" width="{bw}" height="8" rx="4"/></clipPath><g clip-path="url(#lb)"{c.a("sx", .3)}>')
    for l in top:
        w = bw * l["bytes"] / tot
        c.add(f'<rect x="{x:.1f}" y="72" width="{w + .5:.1f}" height="8" fill="{l.get("color") or INDIGO_HI}"/>'); x += w
    c.add('</g>')
    for i, l in enumerate(top):
        cx, cy = 460 + (i % 2) * 150, 112 + (i // 2) * 34
        c.add(f'<circle cx="{cx + 4}" cy="{cy - 4}" r="4" fill="{l.get("color") or INDIGO_HI}"{c.a("fu", .4 + i * .06)}/>')
        c.text(cx + 14, cy, l["name"], "i400", 13, TEXT2, delay=.4 + i * .06)
        c.text(cx + 14, cy + 16, f"{l['bytes'] * 100 / tot:.1f}%", "m500", 11, MUTED, delay=.45 + i * .06)
    if DATA.get("sample"): c.text(W - 24, 236, "sample data", "m500", 10, MUTED, anchor="end", cls="fi", delay=.5)
    return c.render()

def streak():
    last = today if by_date.get(today) else today - dt.timedelta(days=1)
    cs = last - dt.timedelta(days=cur - 1) if cur else None
    best, run, bs, be, st0 = 0, 0, None, None, None
    for dd, v in days:
        if v:
            if not run: st0 = dd
            run += 1
            if run > best: best, bs, be = run, st0, dd
        else: run = 0
    c = Card("streak", W, 190, f"{total} contributions in the last 12 months. Current streak {cur} days. Longest streak {best} days.", delay=1.5)
    c.frame()
    mid = W / 2
    for x in (W / 3 + 5, 2 * W / 3 - 5): c.add(f'<line x1="{x:.0f}" x2="{x:.0f}" y1="36" y2="154" stroke="{BORDER}"/>')
    cx = W / 6
    c.text(cx, 90, f"{total:,}", "i800", 34, TEXT, anchor="middle", delay=.1)
    c.text(cx, 118, "Contributions, last 12 months", "i400", 13, TEXT2, anchor="middle", delay=.15)
    c.text(cx, 140, _range(days[0][0], today), "m500", 11, MUTED, anchor="middle", delay=.2)
    frac = min(1, cur / best) * 100 if best else 0
    c.add(f'<circle cx="{mid}" cy="78" r="38" fill="none" stroke="{BORDER}" stroke-width="6"/>')
    c.add(f'<circle cx="{mid}" cy="78" r="38" fill="none" stroke="{INDIGO}" stroke-width="6" stroke-linecap="round" pathLength="100" '
          f'stroke-dasharray="{frac:.1f} 100" transform="rotate(-90 {mid} 78)"{c.a("rg", .2)}/>')
    c.text(mid, 87, str(cur), "i800", 28, TEXT, anchor="middle", delay=.3)
    c.text(mid, 144, "Current streak", "i600", 13, TEXT, anchor="middle", delay=.35)
    c.text(mid, 162, _range(cs, last) if cs else "No active streak", "m500", 11, MUTED, anchor="middle", delay=.4)
    cx = 5 * W / 6
    c.text(cx, 90, str(best), "i800", 34, TEXT, anchor="middle", delay=.45)
    c.text(cx, 118, "Longest streak, days", "i400", 13, TEXT2, anchor="middle", delay=.5)
    c.text(cx, 140, _range(bs, be) if bs else "", "m500", 11, MUTED, anchor="middle", delay=.55)
    return c.render()

# ---- 4. repo cards ------------------------------------------------------------------------
RW = 392  # repo cards sit two per row in the README

def _blurb(r):
    return DATA.get("repos", {}).get(r["name"], {}).get("description") or r["blurb"]

def repo(i, r, nlines, has_meta):
    meta = DATA.get("repos", {}).get(r["name"], {})
    blurb = _blurb(r)
    lines = wrap(blurb, "i400", 13, RW - 48, nlines)
    h = 64 + 20 * nlines + 40 + (20 if has_meta else 0)
    c = Card(f"repo-{r['name'].lower()}", RW, h, f"{r['title']}: {blurb} ({r['stack']})", delay=2.1 + (i // 2) * 0.25 + (i % 2) * 0.1)
    c.frame()
    c.text(24, 42, r["title"], "i600", 17, TEXT)
    for j, ln in enumerate(lines):
        c.text(24, 68 + j * 20, ln, "i400", 13, TEXT2, delay=0.08)
    fy = h - 22 - (20 if has_meta else 0)
    c.text(24, fy, r["stack"].replace(" · ", "  ·  "), "m500", 11, INDIGO_HI, delay=.18)
    bits = []
    if meta.get("stars"): bits.append(f"{meta['stars']} stars")
    if meta.get("forks"): bits.append(f"{meta['forks']} forks")
    if meta.get("pushed"):
        p = dt.date.fromisoformat(meta["pushed"][:10]); bits.append(f"updated {MON[p.month - 1]} {p.year}")
    if has_meta:
        x, my = 24, fy + 20
        if meta.get("language"):
            c.add(f'<circle cx="{x + 4}" cy="{my - 4}" r="4" fill="{meta.get("language_color") or INDIGO_HI}"{c.a("fu", .2)}/>')
            c.text(x + 14, my, meta["language"], "m500", 11, TEXT2, delay=.2); x += 26 + tw(meta["language"], "m500", 11)
        if bits: c.text(x, my, "  ·  ".join(bits), "m500", 11, MUTED, delay=.22)
    return c.render()

# ---- 5. contribution graph ----------------------------------------------------------------
def graph():
    c = Card("graph", W, 244, f"Contribution graph for the last year, {total} contributions.", delay=3.4)
    c.frame()
    c.text(30, 44, "Contribution graph", "i600", 18, TEXT)
    c.text(W - 30, 44, f"{total} contributions{SAMPLE_NOTE}", "m500", 12, MUTED, anchor="end", delay=.05)
    nz = sorted(v for _, v in days if v)
    q = [nz[int(len(nz) * f) - 1] if nz else 1 for f in (.25, .5, .75)]
    lv = lambda v: 0 if v == 0 else 1 if v <= q[0] else 2 if v <= q[1] else 3 if v <= q[2] else 4
    cols = [ELEV, mix(INDIGO, SURFACE, .35), mix(INDIGO, SURFACE, .6), mix(INDIGO, SURFACE, .85), INDIGO_HI]
    first = days[0][0]; sun0 = first - dt.timedelta(days=(first.weekday() + 1) % 7)
    x0, y0, pitch, cell = 30, 100, 14, 11
    last_label = -9
    cells = defaultdict(list); seen_m = {}
    for dd, v in days:
        wk = (dd - sun0).days // 7; row = (dd.weekday() + 1) % 7
        cells[wk].append(f'<rect x="{x0 + wk * pitch}" y="{y0 + row * pitch}" width="{cell}" height="{cell}" rx="2.5" fill="{cols[lv(v)]}"/>')
        if dd.day <= 7 and row == 0 and (dd.year, dd.month) not in seen_m and wk - last_label >= 3:
            seen_m[(dd.year, dd.month)] = 1; last_label = wk
            c.text(x0 + wk * pitch, 88, MON[dd.month - 1], "m500", 11, MUTED, delay=wk * .02)
    for wk in sorted(cells):
        c.add(f'<g{c.a("fi", 0.1 + wk * 0.022)}>{"".join(cells[wk])}</g>')
    ly = 218
    c.text(W - 30 - 5 * pitch - 34, ly + 9, "Less", "m500", 11, MUTED, anchor="end", cls="fi", delay=2.2)
    for k in range(5):
        c.add(f'<rect x="{W - 30 - 5 * pitch - 24 + k * pitch}" y="{ly}" width="{cell}" height="{cell}" rx="2.5" fill="{cols[k]}"{c.a("fi", 2.2)}/>')
    c.text(W - 30 + 4, ly + 9, "More", "m500", 11, MUTED, anchor="end", cls="fi", delay=2.2)
    return c.render()

# ---- build --------------------------------------------------------------------------------
def main():
    print(f"{'STATIC preview' if STATIC else 'Animated build'} -> {OUT.relative_to(ROOT)}/")
    names = [hero()]
    for i, t in enumerate(CFG["tiles"]): names.append(tile(i, t))
    if "stats" in DATA: names += [stats(), streak()]
    names.append(activity())
    nl = max(len(wrap(_blurb(r), "i400", 13, RW - 48, 4)) for r in CFG["repos"])
    hm = any(DATA.get("repos", {}).get(r["name"]) for r in CFG["repos"])
    for i, r in enumerate(CFG["repos"]): names.append(repo(i, r, nl, hm))
    names.append(graph())
    if STATIC:
        imgs = "".join(f'<img src="{n}.svg" width="{"32.5%" if n.startswith("tile") else "49%"}">' if n.startswith(("tile", "repo")) else f'<img src="{n}.svg">' for n in names)
        (OUT / "index.html").write_text(
            '<!doctype html><meta charset="utf-8"><body style="background:#000;max-width:830px;margin:24px auto;'
            'line-height:0"><style>img{display:block;margin:0 auto 14px;max-width:100%}img[width]{display:inline-block;margin:0 .4% 14px}'
            f'</style>{imgs}</body>', encoding="utf-8")

if __name__ == "__main__":
    main()
