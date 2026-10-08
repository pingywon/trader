"""Audit helper: small direct tests, one per code-level finding. Nothing here
touches the network; the Alpaca SDK client is only constructed, never called."""
import inspect
import os
import pathlib
import sys

os.environ["ALPACA_API_KEY"] = "PKAUDITDUMMYKEY00000"
os.environ["ALPACA_API_SECRET"] = "audit-dummy-secret"

from alpaca.trading.enums import OrderStatus  # noqa: E402

from insider_tracker import alpaca_client, cli, edgar, filters, sizer  # noqa: E402

CACHE = pathlib.Path(sys.argv[1])
cfg = filters.FilterConfig(True, True, ("director", "ceo", "cfo", "chief", "president"), 0)
tiers = tuple(sizer.Tier(a, b, n) for a, b, n in [(0, 5e4, 100), (5e4, 2.5e5, 300), (2.5e5, 1e6, 800), (1e6, 5e6, 1500), (5e6, 999999999, 3000)])
scfg = sizer.SizingConfig(tiers, 0.05)


def head(n, t):
    print(f"\n[{n}] {t}")


head(1, "ALPACA_PAPER: which values send orders to the LIVE endpoint?")
for v in ["true", "TRUE", "1", "yes", "on", "y", "paper", "ture", "", "false", "0"]:
    os.environ["ALPACA_PAPER"] = v
    c = alpaca_client.AlpacaClient()
    base = c.client._base_url if hasattr(c.client, "_base_url") else "?"
    print(f"    ALPACA_PAPER={v!r:9} -> paper={str(c.paper):5}  {base}")
os.environ["ALPACA_PAPER"] = "true"


def mk(**kw):
    base = dict(accession="x", filing_url="", period_of_report=None, issuer_cik="1", issuer_name="Example Co", symbol="EXMP",
                owner_name="Doe Jane", owner_cik="2", is_director=False, is_officer=True, is_ten_percent=False,
                officer_title="", tx_date="2026-10-07", tx_code="P", acquired_disposed="A", shares=1000.0,
                price_per_share=20.0, dollars=20000.0, is_10b5_1=False)
    base.update(kw)
    return edgar.Transaction(**base)


head(2, "Role filter: do titles the README calls 'lower-level' get through?")
for title in ["Vice President, Sales", "Senior Vice President", "Assistant Vice President", "Chief Executive Officer", "Treasurer", "General Counsel"]:
    d = filters.evaluate(mk(officer_title=title), cfg)
    print(f"    {title:28} -> {'ACCEPT' if d.accept else 'reject'}")

head(3, "Sizing uses the first accepted row, not the whole purchase (real filing: COE, 2026-10-08)")
txs = edgar._parse_ownership_xml((CACHE / "0002029760-26-000010.xml").read_text(), "0002029760-26-000010", "")
rows = [t for t in txs if t.tx_code == "P"]
total = sum(t.dollars for t in rows)
print(f"    purchase rows: {len(rows)}   first row ${rows[0].dollars:,.0f}   whole filing ${total:,.0f}")
print(f"    tool sizes on first row -> ${sizer.size_notional(rows[0].dollars, 1e6, scfg):,.0f}    sized on the total -> ${sizer.size_notional(total, 1e6, scfg):,.0f}")

head(4, "Amended filings (4/A) are treated as new signals (real filings: GOAI)")
for acc in ("0001493152-26-046284", "0001493152-26-046286"):
    body = (CACHE / f"{acc}.xml").read_text()
    t = edgar._parse_ownership_xml(body, acc, "")[0]
    d = filters.evaluate(t, cfg)
    print(f"    {acc}  form 4/A, purchase dated {t.tx_date}  -> {'ACCEPT' if d.accept else 'reject'}  ({t.symbol} ${t.dollars:,.0f})")
print("    'documentType' referenced in edgar.py:", "documentType" in inspect.getsource(edgar), "  | tx_date compared to today anywhere:", "tx_date" in inspect.getsource(cli) or "tx_date" in inspect.getsource(filters))

head(5, "10b5-1 checkbox is ignored (real filing: UXIN, 2026-10-08)")
body = (CACHE / "0001493152-26-046274.xml").read_text()
t = edgar._parse_ownership_xml(body, "0001493152-26-046274", "")[0]
print(f"    <aff10b5One> in the XML: {'<aff10b5One>1</aff10b5One>' in body}   element the code reads ('rule10b5_1Flag') present: {'rule10b5_1Flag' in body}")
print(f"    parser says is_10b5_1={t.is_10b5_1}   filter -> {'ACCEPT' if filters.evaluate(t, cfg).accept else 'reject'}")
print("    'aff10b5One' referenced in edgar.py:", "aff10b5One" in inspect.getsource(edgar))

head(6, "config.yaml 'execution' block is never read")
src = "".join(inspect.getsource(m) for m in (cli, alpaca_client, edgar, filters, sizer))
for key in ("execution", "order_type", "time_in_force", "skip_non_fractionable", "fractionable"):
    hits = [ln.strip() for ln in src.splitlines() if key in ln and not ln.strip().startswith("#")]
    print(f"    {key:22} code references: {len(hits)}  {hits[:2] if hits else ''}")

head(7, "A network error during the symbol lookup is recorded as 'not tradable'")


class Boom:
    def get_asset(self, s):
        raise ConnectionError("simulated outage")


c = alpaca_client.AlpacaClient()
c.client = Boom()
print(f"    asset_tradable('AAPL') during an outage -> {c.asset_tradable('AAPL')}   (cli.py then marks the filing skipped for good)")

head(8, "Order status is stored as the enum's name, not its value")
print(f"    str(OrderStatus.ACCEPTED) -> {str(OrderStatus.ACCEPTED)!r}   .value -> {OrderStatus.ACCEPTED.value!r}")

head(9, "Sizing edge cases")
print(f"    equity $15      -> order ${sizer.size_notional(20000, 15, scfg):.2f}   (Alpaca's minimum is $1)")
print(f"    insider $80     -> order ${sizer.size_notional(80, 100000, scfg):.2f}   (larger than the insider's own purchase)")
print(f"    insider $1.2bn  -> order ${sizer.size_notional(1.2e9, 100000, scfg):.2f}   (falls off the top tier)")

head(10, "What the code never asks Alpaca")
for m in ("get_all_positions", "get_open_position", "get_orders", "get_order_by_id", "cancel_order", "close_position", "buying_power", "client_order_id", "get_clock"):
    print(f"    {m:20} used: {m in src}")
