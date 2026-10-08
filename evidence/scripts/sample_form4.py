"""Audit helper: pull several pages of the owner=only Form 4 feed, cache the
XML, and tally what the tracker's parser and filter make of real filings."""
import collections, json, pathlib, re, sys, time
import xml.etree.ElementTree as ET
import feedparser
from dotenv import load_dotenv
load_dotenv()
from insider_tracker import edgar, filters

CACHE = pathlib.Path(sys.argv[1]); CACHE.mkdir(parents=True, exist_ok=True)
PAGES = int(sys.argv[2])
BASE = edgar.EDGAR_BASE + "/cgi-bin/browse-edgar?action=getcurrent&company=&dateb=&output=atom&type=4&owner=only&count=100"

refs, form_of = {}, {}
with edgar._client() as c:
    for p in range(PAGES):
        f = CACHE / f"owneronly_p{p}.atom"
        if not f.exists():
            f.write_text(edgar._get(c, BASE + f"&start={p*100}").text, encoding="utf-8"); time.sleep(0.4)
        for e in feedparser.parse(f.read_text(encoding="utf-8")).entries:
            m = edgar._INDEX_RE.search(e.get("link", ""))
            if not m or m.group(3) in refs: continue
            refs[m.group(3)] = edgar.FilingRef(m.group(3), m.group(1), edgar._parse_dt(e.get("updated")), e.get("title", ""), e.get("link", ""))
            form_of[m.group(3)] = e["tags"][0]["term"] if e.get("tags") else "?"
    ts = [r.filed_at for r in refs.values()]
    print(f"filings sampled             : {len(refs)}   feed form types: {dict(collections.Counter(form_of.values()))}")
    print(f"window (UTC)                : {min(ts):%Y-%m-%d %H:%M} -> {max(ts):%Y-%m-%d %H:%M}")
    for acc, ref in refs.items():
        x = CACHE / f"{acc}.xml"
        if x.exists(): continue
        base = f"{edgar.EDGAR_BASE}/Archives/edgar/data/{int(ref.cik)}/{acc.replace('-', '')}/"
        listing = edgar._get(c, base + "index.json").json()
        name = edgar._pick_primary_xml(listing)
        (CACHE / f"{acc}.index.json").write_text(json.dumps(listing), encoding="utf-8")
        x.write_text(edgar._get(c, base + name).text if name else "", encoding="utf-8")
        (CACHE / f"{acc}.name").write_text(name or "", encoding="utf-8")
        time.sleep(0.25)

cfg = filters.FilterConfig(True, True, ("director", "ceo", "cfo", "chief", "president"), 0)
codes, reasons, doc_types = collections.Counter(), collections.Counter(), collections.Counter()
aff_present = aff_checked = flag_present = fn_10b5 = 0
accepted, multi_p, vp_only, amend_ok, aff_missed, joint = [], [], [], [], [], 0
for acc, ref in refs.items():
    body = (CACHE / f"{acc}.xml").read_text(encoding="utf-8")
    if not body: reasons["no xml found"] += 1; continue
    try: root = ET.fromstring(body)
    except ET.ParseError: reasons["xml parse error"] += 1; continue
    dt = (root.findtext("documentType") or "?").strip(); doc_types[dt] += 1
    aff = root.find("aff10b5One"); checked = aff is not None and (aff.text or "").strip() in ("1", "true")
    aff_present += aff is not None; aff_checked += checked
    flag_present += "rule10b5_1Flag" in body
    if len(root.findall("reportingOwner")) > 1: joint += 1
    txs = edgar._parse_ownership_xml(body, acc, "")
    if not txs: reasons["no non-derivative transactions"] += 1; continue
    fn_10b5 += txs[0].is_10b5_1
    if checked and not txs[0].is_10b5_1:
        aff_missed.append((txs[0].symbol, sorted({t.tx_code for t in txs})))
    p_rows = [t for t in txs if t.tx_code == "P" and t.acquired_disposed in ("", "A")]
    hit, last = None, ""
    for t in txs:
        codes[t.tx_code] += 1
        d = filters.evaluate(t, cfg)
        if d.accept and hit is None: hit = t
        elif not d.accept: last = d.reason
    if hit:
        reasons["ACCEPTED -> would buy"] += 1
        tl = (hit.officer_title or "").lower()
        accepted.append(dict(acc=acc, form=dt, sym=hit.symbol, who=hit.owner_name, title=hit.officer_title, director=hit.is_director,
                             first_row=round(hit.dollars), total=round(sum(t.dollars for t in p_rows)), rows=len(p_rows), filed=f"{ref.filed_at:%m-%d %H:%M}"))
        if len(p_rows) > 1: multi_p.append((hit.symbol, len(p_rows), round(hit.dollars), round(sum(t.dollars for t in p_rows))))
        if dt == "4/A": amend_ok.append(hit.symbol)
        if not hit.is_director and "president" in tl and not any(k in tl for k in ("chief", "ceo", "cfo")) and "vice" in tl: vp_only.append((hit.symbol, hit.officer_title))
    else:
        reasons[re.sub(r"\s*\(.*", "", re.sub(r"\$[\d,]+", "$N", re.sub(r"tx_code='(.)'", r"code \1", last)))] += 1
print(f"documentType in the XML     : {dict(doc_types)}")
print(f"joint filings (>1 owner)    : {joint}")
print(f"<aff10b5One> element present: {aff_present}   box checked: {aff_checked}")
print(f"'rule10b5_1Flag' present    : {flag_present}   (the element the code looks for)")
print(f"flagged 10b5-1 by the code  : {fn_10b5}   (footnote text match only)")
print(f"box checked but code missed : {len(aff_missed)}  {aff_missed[:12]}")
print(f"transaction codes (rows)    : {dict(codes.most_common())}")
print("outcome per filing:")
for k, v in reasons.most_common(): print(f"   {v:4d}  {k}")
print("accepted:")
for a in accepted: print("   ", a)
print(f"multi-row purchases (sym, rows, first-row $, total $): {multi_p}")
print(f"accepted only via 'vice president' title: {vp_only}")
print(f"accepted amendments (4/A): {amend_ok}")
json.dump(accepted, open(CACHE / "accepted.json", "w"), indent=1)
