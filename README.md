# Insider Tracker code audit (site)

This branch is the GitHub Pages site for the audit of `main`.
Live at https://pingywon.github.io/trader/

| Path | What it is |
| --- | --- |
| `index.html`, `audit.html` | The built pages: the overview and the full audit. Do not edit by hand. |
| `src/` | Page templates. |
| `favicon.svg` | Site icon. `tools/favicon.py` makes the PNG copies. |
| `tools/data.json` | Numbers behind the two charts. |
| `VERSION` | The version shown in the page footer. |
| `evidence/` | Captured output from every run, plus the scripts that produced it. |
| `img/` | Screenshots rendered from `evidence/`. |

## Rebuild

```
python3 tools/shots.py    # only if evidence/ changed; needs chromium and websocket-client
python3 tools/build.py
```

Bump `VERSION` before each published change.
