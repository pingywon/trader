#!/usr/bin/env python3
"""Render the captured terminal output in evidence/ as PNG screenshots in img/.

The text is shown exactly as captured; only the prompt and comment lines are
tinted. Needs /usr/bin/chromium and the websocket-client package.
"""
import base64
import html
import json
import pathlib
import subprocess
import tempfile
import time
import urllib.request

import websocket

ROOT = pathlib.Path(__file__).resolve().parent.parent
EVID = ROOT / "evidence"
IMG = ROOT / "img"
IMG.mkdir(exist_ok=True)

SHOTS = [
    ("shot-01-live-dry-run", "Unmodified tool, live SEC feed", "01-live-dry-run.txt", None),
    ("shot-02-replay-run", "Replay over 193 real filings", "02-replay-run.txt", None),
    ("shot-03-wire-trace", "Requests sent to Alpaca during the replay", "03-alpaca-wire-trace.txt", None),
    ("shot-04-status", "The tool's own audit log", "04-status.txt", None),
    ("shot-06a-tests", "Direct tests 1 to 5", "06-direct-tests.txt", ("[1]", "[6]")),
    ("shot-06b-tests", "Direct tests 6 to 10", "06-direct-tests.txt", ("[6]", None)),
]

CSS = """
*{box-sizing:border-box}
html,body{margin:0;background:#fff}
body{padding:24px}
.term{width:1040px;border-radius:10px;overflow:hidden;background:#0e1626;
  font:13px/1.55 'JetBrains Mono','DejaVu Sans Mono',monospace;color:#d3dbea;
  font-variant-ligatures:none;font-feature-settings:"liga" 0,"calt" 0}
.bar{background:#18233b;color:#9aa6bf;padding:9px 18px;font-size:12px;letter-spacing:.01em;
  border-bottom:1px solid #26334f}
pre{margin:0;padding:16px 18px 18px;font:inherit;white-space:pre-wrap;overflow-wrap:anywhere}
.p{color:#ffffff;font-weight:600}
.c{color:#7f8cab}
"""


def tint(line):
    esc = html.escape(line)
    if line.startswith("#"):
        return f'<span class="c">{esc}</span>'
    if line.startswith("$ "):
        cmd, sep, note = line.partition("  #")
        out = f'<span class="p">{html.escape(cmd)}</span>'
        if sep:
            out += f'<span class="c">{html.escape(sep + note)}</span>'
        return out
    return esc


def section(text, cut):
    if not cut:
        return text
    start, end = cut
    lines = text.splitlines()
    first = next(i for i, ln in enumerate(lines) if ln.startswith(start))
    last = next((i for i, ln in enumerate(lines) if end and ln.startswith(end)), len(lines))
    head = [lines[0], ""] if first > 0 else []
    return "\n".join(head + lines[first:last]).rstrip() + "\n"


def page(title, text):
    body = "\n".join(tint(ln) for ln in text.rstrip("\n").splitlines())
    return (f"<!doctype html><meta charset=utf-8><style>{CSS}</style>"
            f'<div class="term"><div class="bar">{html.escape(title)}</div><pre>{body}</pre></div>')


def main():
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="shots"))
    port = 9555
    proc = subprocess.Popen(
        ["/usr/bin/chromium", "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
         f"--remote-debugging-port={port}", f"--user-data-dir={tmp / 'profile'}", "--remote-allow-origins=*",
         "--window-size=1100,900", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        ws_url = None
        for _ in range(80):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=1))
                pages = [t for t in tabs if t["type"] == "page"]
                if pages:
                    ws_url = pages[0]["webSocketDebuggerUrl"]
                    break
            except Exception:
                pass
            time.sleep(0.25)
        ws = websocket.create_connection(ws_url, timeout=60)
        n = [0]

        def send(method, params=None):
            n[0] += 1
            ws.send(json.dumps({"id": n[0], "method": method, "params": params or {}}))
            while True:
                msg = json.loads(ws.recv())
                if msg.get("id") == n[0]:
                    if "error" in msg:
                        raise RuntimeError(f"{method}: {msg['error']}")
                    return msg.get("result", {})

        send("Page.enable")
        send("Emulation.setDeviceMetricsOverride", {"width": 1100, "height": 900, "deviceScaleFactor": 2, "mobile": False})
        for name, title, src, cut in SHOTS:
            f = tmp / f"{name}.html"
            f.write_text(page(title, section((EVID / src).read_text(encoding="utf-8"), cut)), encoding="utf-8")
            send("Page.navigate", {"url": f.as_uri()})
            time.sleep(1.2)
            r = send("Runtime.evaluate", {"returnByValue": True, "expression":
                     "(function(){var b=document.querySelector('.term').getBoundingClientRect();"
                     "return JSON.stringify({x:b.x,y:b.y,w:b.width,h:b.height})})()"})
            b = json.loads(r["result"]["value"])
            shot = send("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": True,
                        "clip": {"x": b["x"], "y": b["y"], "width": b["w"], "height": b["h"], "scale": 1}})
            out = IMG / f"{name}.png"
            out.write_bytes(base64.b64decode(shot["data"]))
            print(f"{out.relative_to(ROOT)}  {int(b['w'] * 2)}x{int(b['h'] * 2)}  {out.stat().st_size // 1024} KB")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    main()
