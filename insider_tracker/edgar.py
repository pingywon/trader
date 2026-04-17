"""SEC EDGAR Form 4 fetcher and parser.

EDGAR requires a declared User-Agent with contact info on every request; without it
SEC rate-limits or 403s. We fail loudly if SEC_USER_AGENT isn't set so the user
notices immediately rather than silently polling a dead endpoint.
"""
from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone

import feedparser
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

EDGAR_BASE = "https://www.sec.gov"
FEED_URL = (
    EDGAR_BASE
    + "/cgi-bin/browse-edgar?action=getcurrent&type=4&company=&dateb=&owner=include"
    "&count={count}&output=atom"
)

_INDEX_RE = re.compile(r"/Archives/edgar/data/(\d+)/(\d{18})/([\d\-]+)-index\.htm")


@dataclass(frozen=True)
class FilingRef:
    accession: str
    cik: str
    filed_at: datetime
    title: str
    index_url: str


@dataclass(frozen=True)
class Transaction:
    accession: str
    filing_url: str
    period_of_report: str | None
    issuer_cik: str
    issuer_name: str
    symbol: str
    owner_name: str
    owner_cik: str
    is_director: bool
    is_officer: bool
    is_ten_percent: bool
    officer_title: str
    tx_date: str
    tx_code: str
    acquired_disposed: str
    shares: float
    price_per_share: float
    dollars: float
    is_10b5_1: bool


def _user_agent() -> str:
    ua = os.environ.get("SEC_USER_AGENT", "").strip()
    if not ua or "@" not in ua:
        raise RuntimeError(
            "SEC_USER_AGENT env var must be set to 'Your Name your@email.com'. "
            "SEC blocks requests without a contact User-Agent."
        )
    return ua


def _client() -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": _user_agent(), "Accept-Encoding": "gzip, deflate"},
        timeout=30.0,
        follow_redirects=True,
    )


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def _get(client: httpx.Client, url: str) -> httpx.Response:
    r = client.get(url)
    r.raise_for_status()
    return r


def fetch_feed(count: int = 100) -> list[FilingRef]:
    url = FEED_URL.format(count=count)
    with _client() as c:
        body = _get(c, url).text
    feed = feedparser.parse(body)
    refs: dict[str, FilingRef] = {}
    for entry in feed.entries:
        link = entry.get("link", "")
        m = _INDEX_RE.search(link)
        if not m:
            continue
        cik, _, accession = m.group(1), m.group(2), m.group(3)
        if accession in refs:
            continue
        refs[accession] = FilingRef(
            accession=accession,
            cik=cik,
            filed_at=_parse_dt(entry.get("updated")),
            title=entry.get("title", ""),
            index_url=link,
        )
    return sorted(refs.values(), key=lambda r: r.filed_at, reverse=True)


def _parse_dt(s: str | None) -> datetime:
    if not s:
        return datetime.now(tz=timezone.utc)
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return datetime.now(tz=timezone.utc)


def fetch_transactions(ref: FilingRef) -> list[Transaction]:
    acc_nodashes = ref.accession.replace("-", "")
    base = f"{EDGAR_BASE}/Archives/edgar/data/{int(ref.cik)}/{acc_nodashes}/"
    with _client() as c:
        listing = _get(c, base + "index.json").json()
        xml_name = _pick_primary_xml(listing)
        if not xml_name:
            return []
        xml_url = base + xml_name
        xml_body = _get(c, xml_url).text
    return _parse_ownership_xml(xml_body, ref.accession, xml_url)


def _pick_primary_xml(listing: dict) -> str | None:
    items = listing.get("directory", {}).get("item", [])
    names = [i.get("name", "") for i in items]
    for preferred in ("primary_doc.xml", "ownership.xml", "form4.xml"):
        if preferred in names:
            return preferred
    # Fallback: any .xml that looks like a Form 4 payload. Skip known sidecar
    # XMLs (FilingSummary, filing fees exhibits, XBRL index) that would parse
    # but aren't ownershipDocument roots.
    _SKIP = ("filingsummary", "exfilingfees", "filing-fees", "index", "metalinks")
    for n in names:
        lc = n.lower()
        if not lc.endswith(".xml"):
            continue
        if any(s in lc for s in _SKIP):
            continue
        return n
    return None


def _text(elem: ET.Element | None, path: str) -> str:
    if elem is None:
        return ""
    child = elem.find(path)
    return (child.text or "").strip() if child is not None and child.text else ""


def _valued(elem: ET.Element | None, path: str) -> str:
    """Form 4 fields commonly wrap their payload in <value>...</value>."""
    if elem is None:
        return ""
    child = elem.find(path)
    if child is None:
        return ""
    v = child.find("value")
    if v is not None and v.text:
        return v.text.strip()
    return (child.text or "").strip()


def _bool(elem: ET.Element | None, path: str) -> bool:
    v = _valued(elem, path) or _text(elem, path)
    return v in ("1", "true", "True")


def _parse_ownership_xml(body: str, accession: str, filing_url: str) -> list[Transaction]:
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return []
    if root.tag != "ownershipDocument":
        return []

    issuer = root.find("issuer")
    issuer_cik = _text(issuer, "issuerCik")
    issuer_name = _text(issuer, "issuerName")
    symbol = _text(issuer, "issuerTradingSymbol").upper().strip()
    # Some issuers report "NONE" / "N/A" when they have no listed ticker.
    if symbol in {"NONE", "N/A", "NA", "-", "--"}:
        symbol = ""
    period = _valued(root, "periodOfReport") or _text(root, "periodOfReport")

    owners = root.findall("reportingOwner")
    if not owners:
        return []
    # Joint filings are rare; attribute to primary reporting owner.
    primary = owners[0]
    oid = primary.find("reportingOwnerId")
    rel = primary.find("reportingOwnerRelationship")
    owner_name = _text(oid, "rptOwnerName")
    owner_cik = _text(oid, "rptOwnerCik")
    is_director = _bool(rel, "isDirector")
    is_officer = _bool(rel, "isOfficer")
    is_ten = _bool(rel, "isTenPercentOwner")
    officer_title = _text(rel, "officerTitle")

    footnote_text = " ".join(
        (fn.text or "") for fn in root.findall("footnotes/footnote")
    ).lower()

    txs: list[Transaction] = []
    for tx in root.findall("nonDerivativeTable/nonDerivativeTransaction"):
        coding = tx.find("transactionCoding")
        amounts = tx.find("transactionAmounts")
        code = _text(coding, "transactionCode") or _valued(coding, "transactionCode")
        shares = _to_float(_valued(amounts, "transactionShares"))
        price = _to_float(_valued(amounts, "transactionPricePerShare"))
        ad = _valued(amounts, "transactionAcquiredDisposedCode")
        tx_date = _valued(tx, "transactionDate")
        tx_10b5 = _bool(coding, "rule10b5_1Flag")
        is_10b5 = (
            tx_10b5
            or "10b5-1" in footnote_text
            or "rule 10b5" in footnote_text
        )
        txs.append(
            Transaction(
                accession=accession,
                filing_url=filing_url,
                period_of_report=period or None,
                issuer_cik=issuer_cik,
                issuer_name=issuer_name,
                symbol=symbol,
                owner_name=owner_name,
                owner_cik=owner_cik,
                is_director=is_director,
                is_officer=is_officer,
                is_ten_percent=is_ten,
                officer_title=officer_title,
                tx_date=tx_date,
                tx_code=code,
                acquired_disposed=ad,
                shares=shares,
                price_per_share=price,
                dollars=shares * price,
                is_10b5_1=is_10b5,
            )
        )
    return txs


def _to_float(s: str) -> float:
    if not s:
        return 0.0
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return 0.0
