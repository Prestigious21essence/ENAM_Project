"""Concall transcripts for any NSE ticker: the last 4 quarters, as text per page.

get_transcripts("TCS") ->
  {"ticker", "transcripts": [{"quarter", "quarter_end", "call_date", "url", "n_pages", "chars",
                              "scanned", "source" ("screener" / "nse"), "detected_by", "screener_label"}],
   "missing":  [{"quarter", "quarter_end", "reason"}],
   "rejected": [{"url", "reason", ...}]          (duplicates, failed downloads, mislabelled links)
   "timings":  {"seconds": ..., "downloads": ...}}

How it works:
  1. screener's concall links (M2) -> download (pdf_text.get_pdf_path) -> text per page
     -> cached as JSON by URL in data/cache/docs/  (each document is processed once, ever)
  2. the REAL quarter and call date are read from the first pages with rules
     ("quarter ended September 30, 2026", "Q2 FY27", "held on 29th October 2026");
     the cheap LLM is asked only when the rules find nothing. Screener's own labels are
     not trusted (TCS lists a Jul 2025 call under "Jul 2026").
  3. one transcript per quarter; the 4 most recent quarters are kept
  4. a quarter with no transcript on screener (or a dead link) -> the company's NSE filings
     for the weeks after that quarter end that mention "transcript" (BSE is blocked from Render)
  5. a scanned PDF (no text layer) is kept but flagged; a quarter still missing is recorded

get_pages(url) -> the cached list of page texts for one document (for M5).

Usage:  python pull\\docs.py TCS ASIANPAINT SHAILY
"""
import hashlib
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta

import pymupdf

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from ingest.screener import get_company
from pdf_text import get_pdf_path

DOCS_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "cache", "docs")
QUARTERS_WANTED = 4
MAX_LINKS_TRIED = 10          # screener links looked at per company (each is cached after once)
MIN_CALL_AGE_DAYS = 30        # a quarter is "expected" only once its call has likely happened
SCANNED_CHARS_PER_PAGE = 200  # below this the PDF has no useful text layer
MIN_TRANSCRIPT_CHARS = 8000   # a 1-page "transcript is on our website" letter is not a transcript

MONTHS = {"january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7,
          "august": 8, "september": 9, "october": 10, "november": 11, "december": 12}
MONTH_PATTERN = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*"
# "September 30, 2026" | "30th September 2026" | "30 Sep 2026" | "Sep 30th, 2026" | "30.09.2026" | "30/09/2026"
DATE_PATTERN = (r"(?:" + MONTH_PATTERN + r"\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})"
                r"|(\d{1,2})(?:st|nd|rd|th)?\s+" + MONTH_PATTERN + r"\.?,?\s+(\d{4})"
                r"|(\d{1,2})[./-](\d{1,2})[./-](\d{4}))")


# ---------- dates and quarters ----------

def parse_date_match(m, offset=0):
    """A DATE_PATTERN match (groups offset..offset+8) -> date or None."""
    g = m.groups()[offset:offset + 9]
    try:
        if g[0]:
            return date(int(g[2]), month_number(g[0]), int(g[1]))
        if g[3]:
            return date(int(g[5]), month_number(g[4]), int(g[3]))
        if g[6]:
            return date(int(g[8]), int(g[7]), int(g[6]))
    except ValueError:
        return None
    return None


def month_number(prefix):
    prefix = prefix.lower()[:3]
    for name in MONTHS:
        if name.startswith(prefix):
            return MONTHS[name]
    return 1


def quarter_end_of(d):
    """The quarter-end date that contains d (31 Mar / 30 Jun / 30 Sep / 31 Dec)."""
    if d.month <= 3:
        return date(d.year, 3, 31)
    if d.month <= 6:
        return date(d.year, 6, 30)
    if d.month <= 9:
        return date(d.year, 9, 30)
    return date(d.year, 12, 31)


def previous_quarter_end(d):
    """The last quarter-end strictly before d (a call in October is about the September quarter)."""
    this = quarter_end_of(d)
    return quarter_end_of(this - timedelta(days=95)) if this >= d else this


def quarter_end_from_fy(q, fy):
    """Q2 of FY27 -> 30 Sep 2026."""
    if fy < 100:
        fy = 2000 + fy
    if q == 1:
        return date(fy - 1, 6, 30)
    if q == 2:
        return date(fy - 1, 9, 30)
    if q == 3:
        return date(fy - 1, 12, 31)
    return date(fy, 3, 31)


def quarter_label(quarter_end):
    """date(2026, 9, 30) -> 'Q2 FY27'."""
    if quarter_end.month == 3:
        return "Q4 FY" + str(quarter_end.year)[-2:]
    fy = quarter_end.year + 1
    q = {6: 1, 9: 2, 12: 3}[quarter_end.month]
    return "Q" + str(q) + " FY" + str(fy)[-2:]


def expected_quarters(today=None, n=QUARTERS_WANTED):
    """The n most recent quarter ends whose call has probably happened."""
    today = today or date.today()
    q = quarter_end_of(today)
    result = []
    while len(result) < n:
        if (today - q).days >= MIN_CALL_AGE_DAYS:
            result.append(q)
        q = quarter_end_of(q - timedelta(days=95))
    return result


# ---------- reading the quarter from the text (rules first) ----------

def detect_quarter(text):
    """(quarter_end, call_date, how) from the first pages of a transcript. Rules only."""
    flat = " ".join(text.split())
    low = flat.lower()
    quarter_end = None
    how = None

    # 1. "quarter (and half year) ended (on) September 30, 2026"
    m = re.search(r"quarter[^.]{0,60}?ended\s+(?:on\s+)?" + DATE_PATTERN, low)
    if m:
        d = parse_date_match(m)
        if d:
            quarter_end = quarter_end_of(d)
            how = "quarter ended <date>"

    # 2. "Q2 FY27" / "Q2H1FY27" / "Q1 FY2027"
    if quarter_end is None:
        m = re.search(r"\bq([1-4])\s*(?:&|and)?\s*(?:h1|h2|9m)?\s*fy\s*'?(\d{2}|\d{4})\b", low)
        if m:
            quarter_end = quarter_end_from_fy(int(m.group(1)), int(m.group(2)))
            how = "Qn FYyy tag"

    # 3. the call date: "held on (Thursday,) 29th October 2026"
    call_date = None
    m = re.search(r"held\s+on\s+(?:[a-z]+day,?\s+)?" + DATE_PATTERN, low)
    if m:
        call_date = parse_date_match(m)
    if call_date is None:
        # "Earnings Conference Call October 08, 2026" / "Transcript Date: July 29, 2026"
        m = re.search(r"(?:conference call|earnings call|transcript)[^.]{0,40}?" + DATE_PATTERN, low)
        if m:
            call_date = parse_date_match(m)

    if quarter_end is None and call_date is not None:
        quarter_end = previous_quarter_end(call_date)
        how = "call date"
    return quarter_end, call_date, how


def detect_quarter_llm(text):
    """Last resort: ask the cheap model for the quarter end and call date."""
    from llm import call_llm
    prompt = ("This is the start of an Indian company's earnings-call transcript or its covering letter. "
              "Which quarter does the call discuss, and on what date was the call held? Answer only from the text. "
              "Return JSON {\"quarter_end_date\": \"YYYY-MM-DD\" or null, \"call_date\": \"YYYY-MM-DD\" or null}.\n\n"
              + text[:4000])
    try:
        answer = json.loads(call_llm(prompt, json_output=True, purpose="transcript_quarter", temperature=0))
        quarter_end = call_date = None
        if answer.get("quarter_end_date"):
            quarter_end = quarter_end_of(datetime.strptime(answer["quarter_end_date"], "%Y-%m-%d").date())
        if answer.get("call_date"):
            call_date = datetime.strptime(answer["call_date"], "%Y-%m-%d").date()
        return quarter_end, call_date
    except Exception as e:
        print("   LLM quarter detection failed:", repr(e)[:80])
        return None, None


def quarter_from_url(url):
    """A hint from the link itself, for links that can't be downloaded:
    '.../2025-26/q1/...Jul 10, 2025.pdf' -> (30 Jun 2025, 'url: 2025-26/q1')."""
    low = url.lower()
    m = re.search(r"(20\d\d)-(\d\d)/q([1-4])", low)
    if m:
        return quarter_end_from_fy(int(m.group(3)), int(m.group(1)) + 1), "url: " + m.group(0)
    m = re.search(DATE_PATTERN, low.replace("%20", " ").replace("%2c", ","))
    if m:
        d = parse_date_match(m)
        if d:
            return previous_quarter_end(d), "url date " + d.isoformat()
    return None, None


# ---------- one document (cached forever) ----------

def cache_path(url):
    return os.path.join(DOCS_CACHE_DIR, hashlib.sha1(url.encode("utf-8")).hexdigest() + ".json")


def process_document(url):
    """Download + text per page + quarter detection, cached by URL. Never raises:
    a failure is returned as {"url", "error"}."""
    os.makedirs(DOCS_CACHE_DIR, exist_ok=True)
    path = cache_path(url)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        doc["from_cache"] = True
        return doc

    started = time.time()
    doc = {"url": url, "processed_on": date.today().isoformat()}
    try:
        pdf = pymupdf.open(get_pdf_path(url))
        pages = []
        for i in range(len(pdf)):
            pages.append(pdf[i].get_text())
        pdf.close()
    except Exception as e:
        doc["error"] = repr(e)[:160]
        doc["seconds"] = round(time.time() - started, 1)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f)
        return doc

    chars = sum(len(p) for p in pages)
    doc["pages"] = pages
    doc["n_pages"] = len(pages)
    doc["chars"] = chars
    doc["scanned"] = len(pages) > 0 and chars / len(pages) < SCANNED_CHARS_PER_PAGE

    head = "\n".join(pages[:3])
    quarter_end, call_date, how = detect_quarter(head)
    if quarter_end is None and not doc["scanned"]:
        quarter_end, call_date = detect_quarter_llm(head)
        how = "llm" if quarter_end else None
    doc["quarter_end"] = quarter_end.isoformat() if quarter_end else None
    doc["quarter"] = quarter_label(quarter_end) if quarter_end else None
    doc["call_date"] = call_date.isoformat() if call_date else None
    doc["detected_by"] = how
    doc["seconds"] = round(time.time() - started, 1)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f)
    return doc


def get_pages(url):
    """The page texts of a processed document ([] if it failed)."""
    return process_document(url).get("pages", [])


# ---------- the NSE fallback ----------

def nse_transcript_links(ticker, quarter_end):
    """PDF links of the company's NSE filings in the ~11 weeks after quarter_end that mention a transcript."""
    from ingest.announcements import fetch_nse, make_nse_session
    try:
        session = make_nse_session()
        items = fetch_nse(session, ticker, quarter_end + timedelta(days=1), quarter_end + timedelta(days=75))
    except Exception as e:
        print("   NSE lookup failed for", ticker, quarter_end, ":", repr(e)[:80])
        return []
    links = []
    for item in items:
        text = ((item.get("subject") or "") + " " + (item.get("details") or "")).lower()
        if "transcript" in text and item.get("pdf_url"):
            links.append(item["pdf_url"])
    return links


# ---------- putting it together ----------

def get_transcripts(ticker, n=QUARTERS_WANTED, nse_fallback=True):
    started = time.time()
    ticker = ticker.upper().strip()
    company = get_company(ticker)
    if company is None:
        return None
    wanted = expected_quarters(n=n)
    found = {}            # quarter_end iso -> transcript entry
    rejected = []
    downloads = 0

    def consider(url, source, label=None):
        nonlocal downloads
        doc = process_document(url)
        if not doc.get("from_cache"):
            downloads = downloads + 1
        if "error" in doc:
            hint_end, hint_how = quarter_from_url(url)
            rejected.append({"url": url, "source": source, "screener_label": label, "reason": "download failed: " + doc["error"][:80],
                             "url_hint": (quarter_label(hint_end) + " (" + hint_how + ")") if hint_end else None})
            return
        if doc["chars"] < MIN_TRANSCRIPT_CHARS and not doc["scanned"]:
            rejected.append({"url": url, "source": source, "screener_label": label,
                             "reason": "too short to be a transcript (" + str(doc["chars"]) + " chars, " + str(doc["n_pages"]) + " pages)"})
            return
        if doc["quarter_end"] is None:
            rejected.append({"url": url, "source": source, "screener_label": label, "reason": "quarter not found in the text"
                             + (" (scanned PDF)" if doc["scanned"] else "")})
            return
        key = doc["quarter_end"]
        if key in found:
            rejected.append({"url": url, "source": source, "screener_label": label, "reason": "duplicate of " + doc["quarter"]})
            return
        found[key] = {"quarter": doc["quarter"], "quarter_end": key, "call_date": doc["call_date"], "url": url,
                      "n_pages": doc["n_pages"], "chars": doc["chars"], "scanned": doc["scanned"], "source": source,
                      "detected_by": doc["detected_by"], "screener_label": label}

    # 1. screener's links, newest first, until the wanted quarters are covered
    tried = 0
    for item in company["documents"]["concalls"]:
        if all(q.isoformat() in found for q in wanted) or tried >= MAX_LINKS_TRIED:
            break
        if not item.get("transcript"):
            continue
        tried = tried + 1
        consider(item["transcript"], "screener", item.get("period"))

    # 2. NSE filings for any wanted quarter still missing
    missing = []
    for q in wanted:
        if q.isoformat() in found:
            continue
        if nse_fallback:
            for url in nse_transcript_links(ticker, q):
                consider(url, "nse")
                if q.isoformat() in found:
                    break
        if q.isoformat() not in found:
            missing.append({"quarter": quarter_label(q), "quarter_end": q.isoformat(),
                            "reason": "no transcript on screener or NSE"})

    transcripts = [found[k] for k in sorted(found, reverse=True)][:n]
    return {"ticker": ticker, "name": company["name"], "transcripts": transcripts, "missing": missing,
            "rejected": rejected, "timings": {"seconds": round(time.time() - started, 1), "downloads": downloads,
                                              "links_tried": tried}}


def print_transcripts(result):
    print("\n==========", result["ticker"], "|", result["name"], "==========")
    print("quarter   quarter_end  call_date   pages  chars   source    detected_by            screener_label  url")
    for t in result["transcripts"]:
        print(t["quarter"].ljust(9), t["quarter_end"].ljust(12), str(t["call_date"]).ljust(11), str(t["n_pages"]).rjust(5),
              str(t["chars"]).rjust(7), t["source"].ljust(9), str(t["detected_by"]).ljust(22), str(t["screener_label"]).ljust(15),
              t["url"][:70] + (" [SCANNED]" if t["scanned"] else ""))
    for m in result["missing"]:
        print("MISSING  ", m["quarter"], m["quarter_end"], "-", m["reason"])
    for r in result["rejected"]:
        print("rejected ", str(r.get("screener_label")).ljust(9), r["reason"], "|", r["url"][:70],
              ("| URL says " + r["url_hint"]) if r.get("url_hint") else "")
    print("timings:", result["timings"])


if __name__ == "__main__":
    for symbol in sys.argv[1:] or ["TCS"]:
        result = get_transcripts(symbol)
        if result is None:
            print("\n", symbol, "-> not found on screener")
            continue
        print_transcripts(result)
