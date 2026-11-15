"""Reviewer audit (read-only). Usage: python -I audit_research_reviewer.py <path to finn/backend> [<copy of finn.db>]
Checks research numbers vs screener cells, quotes vs cached PDF pages, verdict consistency, transcript recency."""
import sqlite3, json, os, re, glob, hashlib, sys
from datetime import date
BACK = sys.argv[1]
DB = sys.argv[2] if len(sys.argv) > 2 else os.path.join(BACK, "data", "finn.db")
sys.path.insert(0, BACK)
from ingest.screener import parse_page
from pull.promises import period_bounds
c = sqlite3.connect(DB)
def stage(t, s):
    r = c.execute("select json from research where ticker=? and stage=?", (t, s)).fetchone()
    return json.loads(r[0]) if r else None
tickers = [r[0] for r in c.execute("select distinct ticker from research order by ticker")]

def norm(x):
    for a, b in [("ﬁ","fi"),("ﬂ","fl"),("ﬀ","ff"),("Ư","ff"),("’","'"),("‘","'"),("“",'"'),("”",'"')]:
        x = x.replace(a, b)
    return re.sub(r"[^a-z0-9]", "", x.lower())
_docs = {}
def pages_for(url):
    if url in _docs: return _docs[url]
    p = os.path.join(BACK, "data", "cache", "docs", hashlib.sha1(url.encode()).hexdigest() + ".json")
    pages = None
    if os.path.exists(p):
        d = json.load(open(p, encoding="utf-8"))
        pages = d.get("pages")
    _docs[url] = pages
    return pages
def check_quote(q, url, page):
    pages = pages_for(url)
    if pages is None: return "NO_DOC"
    nq = norm(q)
    if not nq: return "EMPTY"
    for pg in (page, page - 1, page + 1):
        if pg and 1 <= pg <= len(pages) and nq in norm(pages[pg - 1]): return "ok" if pg == page else "ok_adjacent"
    # across page break
    if page and 1 <= page <= len(pages):
        joined = norm((pages[page-2] if page >= 2 else "") + pages[page-1] + (pages[page] if page < len(pages) else ""))
        if nq in joined: return "ok_break"
    whole = norm(" ".join(pages))
    return "WRONG_PAGE" if nq in whole else "NOT_FOUND"

def screener_page(t, statement):
    files = sorted(glob.glob(os.path.join(BACK, "data", "cache", "screener", f"{t}_{statement}_*.html")))
    files = [f for f in files if open(f, encoding="utf-8").read(10) != "404"]
    return parse_page(open(files[-1], encoding="utf-8").read()) if files else None

out = {"fin": [], "quotes": [], "verdicts": [], "transcripts": []}
for t in tickers:
    fin = stage(t, "financials")
    cache = {}
    checked = skipped = 0
    for sec in fin["sections"]:
        for m in sec.get("metrics", []):
            src = m.get("source") or {}
            table, row, col = src.get("table"), src.get("row"), src.get("column")
            v = m.get("value")
            if not isinstance(v, (int, float)) or not table or not row or not col or m.get("unit") == "%" and table == "profit_loss" and row == "Sales": skipped += 1; continue
            stmt = fin["statement"]
            tname = table
            if "(standalone)" in table: stmt = "standalone"; tname = table.replace("(standalone)", "").strip()
            if tname not in ("quarters", "profit_loss", "balance_sheet", "cash_flow", "ratios"): skipped += 1; continue
            if stmt not in cache: cache[stmt] = screener_page(t, stmt)
            pg = cache[stmt]
            if pg is None: skipped += 1; continue
            tb = pg[tname]
            if row not in tb["rows"] or col not in tb["columns"]: skipped += 1; continue
            sv = tb["rows"][row][tb["columns"].index(col)]
            checked += 1
            if sv is None or abs(sv - v) > max(0.5, abs(sv) * 0.005):
                out["fin"].append((t, sec["id"], m["label"], v, sv, f"{tname}/{row}/{col}"))
    print(f"[fin] {t}: {checked} figures checked against the screener cell, {skipped} derived/skipped")

    pr = stage(t, "promises")
    items = []
    for th in pr["threads"]:
        for p in th["promises"]:
            items.append(("promise", th["key"], p["quote"], p["url"], p["page"]))
        for e in th.get("evidence", []) or []:
            if e.get("source") == "transcript":
                items.append(("actual", th["key"], e["quote"], e["url"], e["page"]))
        lat = None
        ev = [e for e in (th.get("evidence") or []) if isinstance(e.get("value"), (int, float))]
        newest = th["promises"][-1]
        lo, hi, d = newest.get("target_low"), newest.get("target_high"), newest.get("direction")
        if ev and lo is not None:
            lat = sorted(ev, key=lambda e: e.get("period_end") or "")[-1]["value"]
            good = th["verdict"] in ("met", "on track")
            bad = th["verdict"] in ("missed", "behind")
            if good and d != "down" and lat < lo: out["verdicts"].append((t, th["key"], th["verdict"], f"latest {lat} < target low {lo}"))
            if bad and hi is not None and lat >= lo and (d != "down"): out["verdicts"].append((t, th["key"], th["verdict"], f"latest {lat} within/above {lo}-{hi}"))
        if th["verdict"] != th["python_verdict"]:
            out["verdicts"].append((t, th["key"], th["verdict"], f"model verdict differs from Python's '{th['python_verdict']}'"))
        # evidence used for a promise must lie inside the target's own period (FY27 = Apr 2026..Mar 2027)
        for p in th["promises"]:
            ce = p.get("call_quarter_end")
            if not ce: continue
            start, _end = period_bounds(p.get("period"), date.fromisoformat(ce))
            for e in (p.get("comparison") or {}).get("used") or []:
                pe = e.get("period_end")
                if start and pe and date.fromisoformat(pe) < start:
                    out["verdicts"].append((t, th["key"], th["verdict"], f"evidence ending {pe} used for a {p.get('period')} target that starts {start}"))
    st = stage(t, "story")
    if st:
        sn = st.get("snapshot") or {}
        for b in sn.get("bullets", []):
            if b.get("kind") == "quote": items.append(("snapshot", "-", b["quote"], b["url"], b["page"]))
        for side in ("bull", "bear"):
            for pnt in st.get(side, []):
                for ci in pnt.get("cites", []):
                    if ci.get("quote") and ci.get("url"): items.append((side, "-", ci["quote"], ci["url"], ci.get("page")))
    res = {}
    for kind, key, q, url, page in items:
        r = check_quote(q, url, page or 0)
        res[r] = res.get(r, 0) + 1
        if r not in ("ok", "ok_adjacent", "ok_break"): out["quotes"].append((t, kind, key, r, page, q[:90]))
    print(f"[quotes] {t}: {len(items)} quotes -> {res}")
    tr = stage(t, "transcripts")
    for x in tr["transcripts"]:
        lag = (date.fromisoformat(x["call_date"]) - date.fromisoformat(x["quarter_end"])).days if x.get("call_date") else None
        flag = "" if lag is not None and 0 <= lag <= 75 else "  <-- CHECK"
        out["transcripts"].append(f"{t} {x['quarter']} call {x.get('call_date')} (+{lag} d) {x['n_pages']}pp {x['source']}{flag}")
    for m in tr.get("missing", []) or []:
        out["transcripts"].append(f"{t} MISSING {m}")
print("\n=== FINANCIAL MISMATCHES ===");  [print(x) for x in out["fin"]] or None
print("\n=== QUOTE PROBLEMS ===");  [print(x) for x in out["quotes"]]
print("\n=== VERDICT FLAGS ===");  [print(x) for x in out["verdicts"]]
print("\n=== TRANSCRIPTS ===");  [print(x) for x in out["transcripts"]]
