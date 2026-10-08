import collections, sys, time
import feedparser, httpx
from dotenv import load_dotenv
load_dotenv()
from insider_tracker import edgar

BASE = edgar.EDGAR_BASE + "/cgi-bin/browse-edgar?action=getcurrent&company=&dateb=&output=atom"
variants = [
    ("tool's query        type=4  owner=include count=100", "&type=4&owner=include&count=100"),
    ("owner=only          type=4  owner=only    count=100", "&type=4&owner=only&count=100"),
    ("tool's query, page 2 (start=100)",                     "&type=4&owner=include&count=100&start=100"),
    ("tool's query, page 3 (start=200)",                     "&type=4&owner=include&count=100&start=200"),
]
tot = []
with edgar._client() as c:
    for label, q in variants:
        body = edgar._get(c, BASE + q).text
        f = feedparser.parse(body)
        types = collections.Counter((e["tags"][0]["term"] if e.get("tags") else "?") for e in f.entries)
        accs = {m.group(3) for e in f.entries if (m := edgar._INDEX_RE.search(e.get("link", "")))}
        f4 = {m.group(3) for e in f.entries if (m := edgar._INDEX_RE.search(e.get("link", ""))) and e.get("tags") and e["tags"][0]["term"] in ("4", "4/A")}
        ts = [edgar._parse_dt(e.get("updated")) for e in f.entries]
        span = (max(ts) - min(ts)) if ts else None
        print(f"{label}\n   entries={len(f.entries)}  distinct filings={len(accs)}  Form 4 or 4/A filings={len(f4)}")
        print(f"   types={dict(types.most_common())}")
        if ts:
            print(f"   newest {max(ts):%H:%M:%S} UTC  oldest {min(ts):%H:%M:%S} UTC  covers {span}")
        tot.append((len(f4), span))
        time.sleep(0.4)

p1, p2, p3 = tot[0], tot[2], tot[3]
print(f"SUMMARY: newest 300 entries of the tool's query hold {p1[0]+p2[0]+p3[0]} Form 4 filings; the 100 the tool reads hold {p1[0]} and span {p1[1]}; the same 100 slots with owner=only hold {tot[1][0]} and span {tot[1][1]}")
