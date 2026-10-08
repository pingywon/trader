"""Audit helper: run the UNMODIFIED tracker over today's real Form 4 filings
while a local stand-in for Alpaca records every HTTP request the SDK sends.

What is real:   the tracker code, the alpaca-py SDK, the 193 SEC filings.
What is not:    the Alpaca endpoint (127.0.0.1 recorder), the keys (dummies),
                the account equity (a made-up $25,000). No order reaches Alpaca.
"""
import http.server
import io
import json
import logging
import os
import pathlib
import sys
import threading
import uuid
from contextlib import redirect_stdout
from datetime import datetime, timezone

import feedparser

CACHE = pathlib.Path(sys.argv[1])
ASSETS = json.load(open(sys.argv[2]))
OUT = pathlib.Path(sys.argv[3])
OUT.mkdir(parents=True, exist_ok=True)
EQUITY = "25000.00"

os.environ.update(ALPACA_API_KEY="PKREPLAYDUMMYKEY0000", ALPACA_API_SECRET="replay-dummy-secret-not-a-real-key", ALPACA_PAPER="true",
                  SEC_USER_AGENT="replay offline@example.invalid")

WIRE = []


class Recorder(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        raw = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)
        WIRE[-1]["status"] = code
        WIRE[-1]["response"] = obj

    def _record(self, body=None):
        h = self.headers
        WIRE.append(dict(method=self.command, path=self.path, body=body, headers={
            "APCA-API-KEY-ID": h.get("APCA-API-KEY-ID"),
            "APCA-API-SECRET-KEY": "(sent, redacted)" if h.get("APCA-API-SECRET-KEY") else None,
            "User-Agent": h.get("User-Agent"),
            "Content-Type": h.get("Content-Type"),
        }))

    def do_GET(self):
        self._record()
        if self.path == "/v2/account":
            return self._send(200, dict(id=str(uuid.uuid4()), account_number="PA-REPLAY", status="ACTIVE", currency="USD",
                                        cash=EQUITY, portfolio_value=EQUITY, equity=EQUITY, last_equity=EQUITY, buying_power=EQUITY,
                                        pattern_day_trader=False, trading_blocked=False, transfers_blocked=False, account_blocked=False,
                                        created_at="2026-04-10T20:54:29Z", shorting_enabled=False, multiplier="1",
                                        long_market_value="0", short_market_value="0", initial_margin="0", maintenance_margin="0",
                                        daytrade_count=0, sma="0"))
        if self.path.startswith("/v2/assets/"):
            sym = self.path.rsplit("/", 1)[1]
            a = ASSETS.get(sym)
            if not a or "http" in a:
                return self._send(404, {"code": 40410000, "message": f"asset not found for {sym}"})
            return self._send(200, {"id": str(uuid.uuid5(uuid.NAMESPACE_DNS, sym)), "class": "us_equity", "exchange": a["exchange"], "symbol": sym,
                                    "name": a.get("name") or sym, "status": "active", "tradable": a["tradable"], "marginable": True,
                                    "shortable": True, "easy_to_borrow": True, "fractionable": a["fractionable"]})
        self._send(404, {"message": "not found"})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        self._record(body)
        if self.path != "/v2/orders":
            return self._send(404, {"message": "not found"})
        a = ASSETS.get(body.get("symbol"), {})
        if body.get("notional") is not None and not a.get("fractionable"):
            return self._send(403, {"code": 40310000, "message": "requested asset is not fractionable"})
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        self._send(200, {"id": str(uuid.uuid4()), "client_order_id": str(uuid.uuid4()), "created_at": now, "updated_at": now,
                         "submitted_at": now, "filled_at": None, "expired_at": None, "canceled_at": None, "failed_at": None,
                         "replaced_at": None, "replaced_by": None, "replaces": None,
                         "asset_id": str(uuid.uuid5(uuid.NAMESPACE_DNS, body["symbol"])), "symbol": body["symbol"],
                         "asset_class": "us_equity", "notional": str(body.get("notional")), "qty": None, "filled_qty": "0",
                         "filled_avg_price": None, "order_class": "", "order_type": body["type"], "type": body["type"],
                         "side": body["side"], "position_intent": "buy_to_open", "time_in_force": body["time_in_force"],
                         "limit_price": None, "stop_price": None, "status": "pending_new", "extended_hours": False, "legs": None,
                         "trail_percent": None, "trail_price": None, "hwm": None, "subtag": None, "source": "access_key"})


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Recorder)
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{srv.server_address[1]}"

from alpaca.trading.client import TradingClient  # noqa: E402

from insider_tracker import alpaca_client, cli, edgar  # noqa: E402


class RedirectedTradingClient(TradingClient):
    def __init__(self, key, secret, paper=True, **kw):
        self.would_have_used = "https://paper-api.alpaca.markets" if paper else "https://api.alpaca.markets"
        super().__init__(key, secret, paper=paper, url_override=URL, **kw)


alpaca_client.TradingClient = RedirectedTradingClient


def cached_feed(count=100):
    refs = {}
    for f in sorted(CACHE.glob("owneronly_p*.atom")):
        for e in feedparser.parse(f.read_text(encoding="utf-8")).entries:
            m = edgar._INDEX_RE.search(e.get("link", ""))
            if m and m.group(3) not in refs:
                refs[m.group(3)] = edgar.FilingRef(m.group(3), m.group(1), edgar._parse_dt(e.get("updated")), e.get("title", ""), e.get("link", ""))
    return sorted(refs.values(), key=lambda r: r.filed_at, reverse=True)


def cached_transactions(ref):
    return edgar._parse_ownership_xml((CACHE / f"{ref.accession}.xml").read_text(encoding="utf-8"), ref.accession, "")


cli.fetch_feed = cached_feed
cli.fetch_transactions = cached_transactions

db = OUT / "replay-state.db"
db.unlink(missing_ok=True)


def run(argv, name):
    buf = io.StringIO()
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = logging.StreamHandler(buf)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S"))
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    orig = cli._configure_logging
    cli._configure_logging = lambda verbose: None
    with redirect_stdout(buf):
        rc = cli.main(["--db", str(db)] + argv)
    cli._configure_logging = orig
    text = buf.getvalue()
    (OUT / name).write_text(text, encoding="utf-8")
    print(f"===== insider-tracker {' '.join(argv)}   (exit code {rc})")
    print(text)
    return rc


run(["run"], "run1.txt")
n1 = len(WIRE)
run(["run"], "run2.txt")
run(["status"], "status.txt")

json.dump(WIRE, open(OUT / "wire.json", "w"), indent=1)
print(f"===== requests the SDK sent to the stand-in: {n1} in run 1, {len(WIRE) - n1} in run 2")
for w in WIRE:
    print(f"{w['method']:4} {w['path']:22} -> {w['status']}  " + (json.dumps(w["body"]) if w["body"] else ""))
print("===== headers on the first request:", json.dumps(WIRE[0]["headers"]))
