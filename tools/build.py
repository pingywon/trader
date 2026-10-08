#!/usr/bin/env python3
"""Build index.html and audit.html from the templates in src/.

The version shown in each footer comes from the VERSION file and the chart
numbers from tools/data.json, so the pages cannot drift from either.
"""
import html
import json
import pathlib
import re
import struct
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SHA = "1d095478d7468689d97205bfba629d012f78af02"
FIX = "7962781313b17d34514d2f54658ba152e4534ebb"
PAGES = [("index.src.html", "index.html"), ("audit.src.html", "audit.html")]

version = (ROOT / "VERSION").read_text().strip()
data = json.loads((ROOT / "tools" / "data.json").read_text())


def png_height(name):
    with open(ROOT / "img" / name, "rb") as f:
        head = f.read(24)
    return struct.unpack(">II", head[16:24])[1]


def icon(shape, color, label):
    shapes = {
        "triangle": '<path d="M8 1.5 15 14.5H1z"/>',
        "diamond": '<path d="M8 1 15 8 8 15 1 8z"/>',
        "circle": '<circle cx="8" cy="8" r="6.5"/>',
        "check": '<path d="M8 1a7 7 0 1 0 0 14A7 7 0 0 0 8 1zm3.6 5.3-4.2 4.6-2.9-2.6 1-1.1 1.8 1.6 3.2-3.5z"/>',
    }
    return f'<svg viewBox="0 0 16 16" fill="{color}" role="img" aria-label="{label}">{shapes[shape]}</svg>'


def waffle(groups):
    cells = []
    for g in groups:
        tip = html.escape(f"{g['form']}: {g['what']} ({g['n']} of 100 entries)", quote=True)
        cls = ' class="hit"' if g["hit"] else ""
        cells += [f'<span{cls} data-tip="{tip}"></span>'] * g["n"]
    assert len(cells) == 100, len(cells)
    return "".join(cells)


def keys(groups):
    return "".join(
        f'<li><i class="{"hit" if g["hit"] else ""}"></i><b>{g["n"]}</b><span>{html.escape(g["form"])} {html.escape(g["what"])}</span></li>'
        for g in groups)


def feed_table():
    rows = "".join(
        f'<tr><td>{label}</td><td>{html.escape(g["form"])}</td><td>{html.escape(g["what"])}</td><td class="num">{g["n"]}</td></tr>'
        for label, key in (("As committed", "feed_asis"), ("With owner=only", "feed_fixed")) for g in data[key]["groups"])
    return ('<table><thead><tr><th>Request</th><th>Form</th><th>What it is</th><th class="num">Entries</th></tr></thead>'
            f"<tbody>{rows}</tbody></table>")


def bars():
    total = data["outcomes_total"]
    assert sum(o["n"] for o in data["outcomes"]) == total
    top = max(o["n"] for o in data["outcomes"])
    out = []
    for o in data["outcomes"]:
        pct = o["n"] / total * 100
        code = f" (code {o['code']})" if o["code"] else ""
        tip = html.escape(f"{o['label']}{code}: {o['n']} of {total} filings, {pct:.0f}%", quote=True)
        out.append(f'<div class="bar-row{" hit" if o["hit"] else ""}" data-tip="{tip}"><span class="bl">{html.escape(o["label"])}</span>'
                   f'<span class="bt"><span class="bf" style="width:{o["n"] / top * 100:.1f}%"></span></span><span class="bv">{o["n"]}</span></div>')
    return "".join(out)


def bars_table():
    total = data["outcomes_total"]
    rows = "".join(f'<tr><td>{html.escape(o["label"])}</td><td>{o["code"] or ""}</td><td class="num">{o["n"]}</td></tr>' for o in data["outcomes"])
    return ('<table><thead><tr><th>Outcome</th><th>SEC code</th><th class="num">Filings</th></tr></thead>'
            f'<tbody>{rows}<tr><td><b>Total</b></td><td></td><td class="num"><b>{total}</b></td></tr></tbody></table>')


tokens = {
    "VERSION": version,
    "SHA": SHA,
    "COMMIT": data["commit"],
    "BLOB": f"https://github.com/pingywon/trader/blob/{SHA}",
    "FIX_URL": f"https://github.com/pingywon/trader/commit/{FIX}",
    "FIX": FIX[:7],
    "REPLAY_H": str(png_height("shot-02-replay-run.png")),
    "WAFFLE_ASIS": waffle(data["feed_asis"]["groups"]),
    "WAFFLE_FIXED": waffle(data["feed_fixed"]["groups"]),
    "KEYS_ASIS": keys(data["feed_asis"]["groups"]),
    "KEYS_FIXED": keys(data["feed_fixed"]["groups"]),
    "SPAN_ASIS": data["feed_asis"]["span"],
    "SPAN_FIXED": data["feed_fixed"]["span"],
    "FEED_TABLE": feed_table(),
    "BARS": bars(),
    "BARS_TABLE": bars_table(),
    "ICON_HIGH": icon("triangle", "var(--high)", "High severity"),
    "ICON_MED": icon("diamond", "var(--med)", "Medium severity"),
    "ICON_LOW": icon("circle", "var(--low)", "Low severity"),
    "ICON_GOOD": icon("check", "var(--good)", "Good"),
}

for src, out in PAGES:
    page = (ROOT / "src" / src).read_text(encoding="utf-8")
    for k, v in tokens.items():
        page = page.replace("{{" + k + "}}", v)
    left = re.findall(r"\{\{[A-Z_]+\}\}", page)
    if left:
        sys.exit(f"{src}: unfilled tokens {sorted(set(left))}")
    local = re.findall(r'(?:href|src)="((?:img|evidence)/[^"#]+|favicon\.[a-z]+|apple-touch-icon\.png|audit\.html)"', page)
    missing = [m for m in local if not (ROOT / m).exists() and m != "audit.html"]
    if missing:
        sys.exit(f"{src}: missing files {sorted(set(missing))}")
    (ROOT / out).write_text(page, encoding="utf-8")
    print(f"built {out:11s} version {version}  {len(page) // 1024} KB")
