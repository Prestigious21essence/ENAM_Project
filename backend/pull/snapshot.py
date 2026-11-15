"""The "story" stage: a business snapshot and a bull-vs-bear case, every bullet cited.

build_story("TCS") ->
  {"ticker", "name",
   "snapshot": {"source": {"kind", "label", "url", "pages_used"}, "bullets": [{text, quote, page, url, doc}], ...},
   "bull": [{"text", "cites": [citation...]}], "bear": [...],
   "stats": {...}, "models": {"snapshot": ..., "bullbear": ...}}

Snapshot (max 5 bullets: what it does, segments, revenue mix, customers/geography) from, in order:
  1. the latest investor presentation (screener's PPT link, if within 15 months and it has text)
  2. the latest transcript's opening remarks (up to the first analyst question)
  3. the latest annual report, first 40 pages (ARs are huge)
Prompt: "answer only from the text below; say 'not disclosed' if absent". Each bullet carries a
verbatim quote + page; the quote is verified in Python (M5's find_quote) or the bullet is DROPPED.

Bull vs bear (3 points each) is built ONLY from FINN's own evidence: the numbers sections (screener
{table, column}), the promise verdicts and the transcript quotes behind them. The model may only
point at evidence ids; Python attaches the citation, re-verifies quotes, and drops uncited points.

Usage:  python pull\\snapshot.py TCS ASIANPAINT IRCTC
"""
import hashlib
import json
import os
import re
import sys
import time
from datetime import date, datetime

import pymupdf

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from db import get_conn
from ingest.screener import get_company
from llm import answer_model, call_llm
from pdf_text import get_pdf_path
from pull.docs import get_pages, get_transcripts
from pull.financials import build_numbers
from pull.guidance import find_quote
from pull.promises import VERDICT_MODELS

STORY_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "cache", "story")
PROMPT_VERSION = "v2"      # v2: a bullet's numbers must be in its own quote
PPT_MAX_MONTHS = 15
PPT_MAX_PAGES = 40
AR_MAX_PAGES = 40
OPENING_MAX_PAGES = 8
MAX_EVIDENCE = 36
QUESTION_MARKERS = re.compile(r"(first question (is|comes) from|question (is|comes) from the line of|we('ll| will) (now )?(take|begin|move to) the (first )?question|open the floor for questions)", re.I)

SNAPSHOT_PROMPT = """Below is a document from {company} ({kind}). Pages are marked "[page N]".
Answer ONLY from the text below; if something is not in the text, say "not disclosed" instead of guessing.

Write at most 5 short bullets that tell an investor what this company is:
  1. what it does (products/services and for whom)
  2. its business segments or divisions
  3. revenue mix (by segment, geography or customer type, with the numbers if given)
  4. key customers, markets or scale facts (plants, stores, employees, clients)
  5. anything else structural (ownership, regulation, strategy headline)
Skip a bullet rather than invent it. Each bullet must rest on ONE verbatim quote from the text
(at most 2 sentences, copied exactly) and its page.

Return JSON: {{"bullets": [{{"text": "<= 30 words, plain English", "quote": "verbatim", "page": N}}]}}

Document:
{document}
"""

BULLBEAR_PROMPT = """You are summarising the investment case for {company} using ONLY the evidence items below,
which were produced by an analysis app from primary sources (screener tables, the company's own
earnings-call transcripts). Each item has an id.

Give the 3 strongest BULL points and the 3 strongest BEAR points. Rules:
- Each point is at most 30 words, plain English, and names the 1-2 evidence ids it rests on.
- Use only facts that appear in the evidence. No outside knowledge, no news, no valuation opinion.
- If the evidence does not support 3 points on a side, give fewer.
- Prefer concrete numbers and promise verdicts over generic statements.

Return JSON: {{"bull": [{{"text": "...", "evidence": ["E3", "E7"]}}], "bear": [{{"text": "...", "evidence": ["E12"]}}]}}

Evidence:
{evidence}
"""


# ---------- document helpers ----------

def load_pdf_pages(url, max_pages):
    """Text per page of a PDF (first max_pages), cached here; [] if it can't be read."""
    os.makedirs(STORY_CACHE_DIR, exist_ok=True)
    path = os.path.join(STORY_CACHE_DIR, "pages_" + hashlib.sha1(url.encode("utf-8")).hexdigest() + ".json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    pages = []
    try:
        doc = pymupdf.open(get_pdf_path(url))
        for i in range(min(len(doc), max_pages)):
            pages.append(doc[i].get_text())
        doc.close()
    except Exception as e:
        print("   could not read", url[:80], "->", repr(e)[:80])
        pages = []
    with open(path, "w", encoding="utf-8") as f:
        json.dump(pages, f)
    return pages


def months_ago(period_text):
    """'Nov 2026' -> months between then and today; 999 if unreadable."""
    try:
        d = datetime.strptime(period_text, "%b %Y").date()
    except (TypeError, ValueError):
        return 999
    today = date.today()
    return (today.year - d.year) * 12 + (today.month - d.month)


def has_text(pages):
    total = sum(len(p) for p in pages)
    return len(pages) > 0 and total / len(pages) >= 200 and total >= 3000


def opening_remarks(pages):
    """The transcript pages before the first analyst question (at least 2, at most OPENING_MAX_PAGES)."""
    cut = len(pages)
    for i, page in enumerate(pages):
        if i >= 1 and QUESTION_MARKERS.search(page):
            cut = i + 1
            break
    return pages[:max(2, min(cut, OPENING_MAX_PAGES))]


def pick_source(company, transcripts):
    """Where the snapshot comes from. Returns {"kind", "label", "url", "pages"} or None."""
    for item in company["documents"]["concalls"][:8]:
        url = item.get("ppt")
        if url and months_ago(item.get("period")) <= PPT_MAX_MONTHS:
            pages = load_pdf_pages(url, PPT_MAX_PAGES)
            if has_text(pages):
                return {"kind": "investor presentation", "label": "Investor presentation, " + str(item.get("period")), "url": url, "pages": pages}
    if transcripts:
        t = transcripts[0]
        pages = opening_remarks(get_pages(t["url"]))
        if has_text(pages):
            return {"kind": "earnings-call opening remarks", "label": t["quarter"] + " earnings call, opening remarks", "url": t["url"],
                    "pages": pages, "quarter": t["quarter"]}
    reports = company["documents"]["annual_reports"]
    if reports:
        pages = load_pdf_pages(reports[0]["url"], AR_MAX_PAGES)
        if has_text(pages):
            return {"kind": "annual report", "label": "Annual report " + str(reports[0].get("year")) + ", first " + str(len(pages)) + " pages",
                    "url": reports[0]["url"], "pages": pages}
    return None


def labelled(pages):
    out = []
    for i, p in enumerate(pages):
        out.append("[page " + str(i + 1) + "]\n" + p)
    return "\n".join(out)


# ---------- snapshot ----------

NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def numbers_covered(text, quote):
    """Every number in the bullet text appears in the quote (commas ignored; 20,000 == 20000;
    a number written in the quote as 2.5 billion / 20k counts when the digits match)."""
    quote_digits = set(n.replace(",", "") for n in NUMBER.findall(quote))
    quote_flat = quote.replace(",", "")
    for n in NUMBER.findall(text):
        plain = n.replace(",", "")
        if plain in quote_digits or plain in quote_flat:
            continue
        return False
    return True


def build_snapshot(company_name, source):
    prompt = SNAPSHOT_PROMPT.format(company=company_name, kind=source["kind"], document=labelled(source["pages"]))
    answer = call_llm(prompt, json_output=True, purpose="snapshot", temperature=0)
    model = answer_model(prompt)
    try:
        raw = json.loads(answer)
        items = raw.get("bullets", []) if isinstance(raw, dict) else raw
    except ValueError:
        items = []
    bullets = []
    dropped = 0
    for item in (items or [])[:5]:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "")).strip()
        if not text or "not disclosed" in text.lower():
            continue
        try:
            page = int(item.get("page") or 0)
        except (TypeError, ValueError):
            page = 0
        real_page = find_quote(str(item.get("quote", "")), source["pages"], page)
        if real_page is None:
            dropped = dropped + 1
            continue
        # every number in the bullet must be in its own verified quote (not from another page of the deck)
        if not numbers_covered(text, str(item.get("quote", ""))):
            dropped = dropped + 1
            continue
        bullets.append({"text": text, "quote": item.get("quote"), "page": real_page, "url": source["url"],
                        "doc": source["label"], "kind": "quote"})
    return {"source": {"kind": source["kind"], "label": source["label"], "url": source["url"], "pages_used": len(source["pages"])},
            "bullets": bullets, "extracted": len(items or []), "verified": len(bullets), "dropped": dropped, "model": model}


# ---------- bull vs bear ----------

def load_promises(ticker):
    conn = get_conn()
    row = conn.execute("SELECT status, json FROM research WHERE ticker = ? AND stage = 'promises'", (ticker,)).fetchone()
    conn.close()
    if row and row[0] == "done" and row[1]:
        return json.loads(row[1])
    return None


def evidence_pack(financials, promises):
    """FINN's own findings as numbered items, each carrying its citation."""
    items = []

    def add(text, cite):
        if len(items) < MAX_EVIDENCE:
            items.append({"id": "E" + str(len(items) + 1), "text": text, "cite": cite})

    if financials:
        for section in financials["sections"]:
            table = {"snapshot": "profit_loss", "trajectory": "profit_loss", "balance_sheet": "balance_sheet", "cash_quality": "cash_flow"}.get(section["id"], "profit_loss")
            add(section["title"] + ": " + section["takeaway"],
                {"kind": "screener", "label": section["title"] + " takeaway", "value": "rule-based, from the screener tables", "table": table,
                 "row": "several rows", "column": "see metrics", "url": financials["url"]})
            shown = 0
            for m in section["metrics"]:
                if m["value"] == "n/a" or shown >= 3:
                    continue
                unit = m.get("unit") or ""
                add(m["label"] + " = " + str(m["value"]) + (" " + unit if unit else "") + " (" + str(m["period"]) + ")",
                    {"kind": "screener", "label": m["label"], "value": str(m["value"]) + (" " + unit if unit else ""), "period": m["period"],
                     "table": m["source"]["table"], "row": m["source"]["row"], "column": m["source"]["column"], "url": m["source"]["url"]})
                shown = shown + 1
    if promises:
        add("Credibility: " + promises["scorecard"]["credibility"],
            {"kind": "screener", "label": "Promised vs delivered scorecard", "value": promises["scorecard"]["credibility"], "table": "scorecard",
             "row": "all threads", "column": "verdict counts", "url": None})
        for t in promises["threads"]:
            newest = t["promises"][-1]
            add("Verdict on " + t["metric"] + ": " + t["verdict"].upper() + ". " + (t.get("sentence") or ""),
                {"kind": "quote", "title": "Promise · " + t["metric"], "quote": newest["quote"], "speaker": newest.get("speaker"),
                 "quarter": newest["call_quarter"], "callDate": newest.get("call_date"), "page": newest["page"], "url": newest["url"],
                 "target": str(newest.get("target_text")) + " · " + str(newest.get("period"))})
            for m in t["movement"]:
                if m["change"] in ("lowered", "raised"):
                    who = [p for p in t["promises"] if p["call_quarter"] == m["to_quarter"]]
                    if who:
                        p = who[-1]
                        add("Target for " + t["metric"] + " was " + m["change"] + " in " + m["to_quarter"] + ": " + str(m["from"]) + " -> " + str(m["to"]),
                            {"kind": "quote", "title": "Promise · " + t["metric"], "quote": p["quote"], "speaker": p.get("speaker"),
                             "quarter": p["call_quarter"], "callDate": p.get("call_date"), "page": p["page"], "url": p["url"],
                             "target": str(p.get("target_text")) + " · " + str(p.get("period"))})
            used = []
            for p in t["promises"]:
                for e in p["comparison"].get("used", []):
                    if e.get("source") == "transcript" and e not in used:
                        used.append(e)
            for e in used[-2:]:
                add("Reported " + t["metric"] + " in " + e["call_quarter"] + ": " + str(e.get("value_text")),
                    {"kind": "quote", "title": "Reported · " + t["metric"], "quote": e["quote"], "speaker": e.get("speaker"),
                     "quarter": e["call_quarter"], "callDate": e.get("call_date"), "page": e["page"], "url": e["url"], "target": str(e.get("value_text"))})
    return items


def verify_cite(cite):
    """A quote citation is re-checked against the document page; screener cites pass through."""
    if cite["kind"] != "quote":
        return cite
    pages = get_pages(cite["url"])
    page = find_quote(str(cite.get("quote", "")), pages, int(cite.get("page") or 0))
    if page is None:
        return None
    cite = dict(cite)
    cite["page"] = page
    return cite


def build_bullbear(company_name, evidence):
    lines = []
    for e in evidence:
        lines.append(e["id"] + ": " + e["text"])
    prompt = BULLBEAR_PROMPT.format(company=company_name, evidence="\n".join(lines))
    answer = call_llm(prompt, json_output=True, purpose="bullbear", temperature=0, models=VERDICT_MODELS)
    model = answer_model(prompt, models=VERDICT_MODELS)
    try:
        raw = json.loads(answer)
    except ValueError:
        raw = {}
    by_id = {e["id"]: e for e in evidence}
    result = {"bull": [], "bear": [], "dropped": 0, "model": model}
    for side in ("bull", "bear"):
        for point in (raw.get(side, []) if isinstance(raw, dict) else [])[:3]:
            if not isinstance(point, dict):
                continue
            cites = []
            for eid in point.get("evidence", []) or []:
                e = by_id.get(str(eid).strip().upper())
                if e is None:
                    continue
                cite = verify_cite(e["cite"])
                if cite is not None:
                    cites.append(cite)
            if not cites or not str(point.get("text", "")).strip():
                result["dropped"] = result["dropped"] + 1
                continue
            result[side].append({"text": str(point["text"]).strip(), "cites": cites})
    return result


# ---------- put together ----------

def build_story(ticker, use_cache=True):
    ticker = ticker.upper().strip()
    company = get_company(ticker)
    if company is None:
        return None
    started = time.time()
    docs = get_transcripts(ticker, n=5)
    transcripts = docs["transcripts"] if docs else []
    financials = build_numbers(ticker)
    promises = load_promises(ticker)
    source = pick_source(company, transcripts)
    evidence = evidence_pack(financials, promises)

    key = hashlib.sha1((ticker + "|" + (source["url"] if source else "none") + "|" + json.dumps([e["text"] for e in evidence], ensure_ascii=False)
                        + "|" + PROMPT_VERSION).encode("utf-8")).hexdigest()
    os.makedirs(STORY_CACHE_DIR, exist_ok=True)
    path = os.path.join(STORY_CACHE_DIR, ticker + "_" + key + ".json")
    if use_cache and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    snapshot = build_snapshot(company["name"], source) if source else {"source": None, "bullets": [], "extracted": 0, "verified": 0, "dropped": 0, "model": None,
                                                                         "note": "no presentation, transcript or annual report with readable text"}
    bullbear = build_bullbear(company["name"], evidence) if evidence else {"bull": [], "bear": [], "dropped": 0, "model": None}
    result = {
        "ticker": ticker, "name": company["name"], "snapshot": snapshot,
        "bull": bullbear["bull"], "bear": bullbear["bear"],
        "evidence_count": len(evidence), "promises_available": promises is not None,
        "stats": {"snapshot_extracted": snapshot["extracted"], "snapshot_verified": snapshot["verified"], "snapshot_dropped": snapshot["dropped"],
                  "bullbear_points": len(bullbear["bull"]) + len(bullbear["bear"]), "bullbear_dropped": bullbear["dropped"]},
        "models": {"snapshot": snapshot.get("model"), "bullbear": bullbear.get("model")},
        "seconds": round(time.time() - started, 1), "built_on": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=1, ensure_ascii=False)
    return result


def print_story(r):
    print("\n==========", r["ticker"], "|", r["name"], "| models:", r["models"], "|", r["seconds"], "s ==========")
    s = r["snapshot"]
    print("SNAPSHOT from", s["source"]["label"] if s.get("source") else "nothing", "| extracted", s["extracted"], "verified", s["verified"], "dropped", s["dropped"])
    for b in s["bullets"]:
        print("  •", b["text"], "  [p." + str(b["page"]) + "]")
        print("      \"" + str(b["quote"])[:140] + "\"")
    for side in ("bull", "bear"):
        print(side.upper(), "(" + str(len(r[side])) + ")")
        for p in r[side]:
            cites = []
            for c in p["cites"]:
                cites.append((c["quarter"] + " p." + str(c["page"])) if c["kind"] == "quote" else ("screener " + c["table"] + "/" + str(c["column"])))
            print("  •", p["text"], "  [" + "; ".join(cites) + "]")
    print("evidence items:", r["evidence_count"], "| promises available:", r["promises_available"], "| dropped bull/bear:", r["stats"]["bullbear_dropped"])


if __name__ == "__main__":
    for symbol in sys.argv[1:] or ["TCS"]:
        result = build_story(symbol)
        if result is None:
            print("\n", symbol, "-> not found on screener")
            continue
        print_story(result)
