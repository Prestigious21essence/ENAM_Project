"""Promised vs delivered: did management do what it said on earlier calls?

build_scorecard("TCS") ->
  {"ticker", "name", "threads": [thread...], "scorecard": {counts..., "credibility": "one line"},
   "models": {...}, "tokens": {...}}
thread = {"key", "metric", "promises": [...M5 items with period_end, period_over...],
          "movement": [{"from_quarter", "to_quarter", "change": reiterated|raised|lowered|changed}],
          "dropped": bool, "evidence": [...], "comparison": {...python's arithmetic...},
          "verdict", "sentence", "verdict_model"}

How it works (maths and decisions in Python, words from the models):
  1. M5's promises (pull/guidance.py, last 5 calls) are grouped into THREADS by metric
     (rules), and the target's movement call-to-call is computed: reiterated / raised /
     lowered / changed / dropped (not mentioned on the newest call).
  2. ACTUALS use the company's own definition: the cheap model reads the reported figure
     for each thread metric from every LATER transcript (one call per transcript), and the
     quote is verified in Python exactly like M5. Screener is used only where its definition
     matches (revenue growth, PAT): YoY sales growth / FY sales growth / PAT growth.
  3. Python decides whether the promise's period is over (FY27 -> 31 Mar 2027; "medium term"
     is open-ended and can never be "missed") and compares actual with target.
  4. The STRONGER model writes one verdict per thread (met / missed / partly / on track /
     behind / pending / can't tell) + one sentence citing the promise AND the evidence.
     It may only pick from that list; Python's arithmetic verdict is kept alongside.
  5. Scorecard: counts + one rule-based credibility line.

Usage:  python pull\\promises.py TCS ASIANPAINT
"""
import csv
import hashlib
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from ingest.screener import get_company
from llm import COST_LOG_PATH, answer_model, call_llm
from pull.docs import get_pages, quarter_end_of, quarter_label
from pull.guidance import extract_guidance, find_quote

PROMISES_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "cache", "promises")
# Checked live 2026-11-15 00:10 on the free tier: 2.5-pro 404 (gone), 3.8-flash 503, 3.7-flash 504,
# 3.6-flash answers in ~3 s. So the strongest model that works is 3.6-flash; 3.5-flash is the fallback.
# 00:20: 3.6-flash's free quota is only 20 requests per DAY (quotaId GenerateRequestsPerDayPerProjectPerModel,
# resets at midnight Pacific), and 3.5-flash ran out the same minute; llm.py marks them "out" and the
# lite model finishes the run. The verdict's arithmetic is Python's anyway; the model writes the sentence.
# 15 Nov 18:20: Mistral dropped (no API key could be created on its free plan): Gemini only.
# The fallback routing in llm.py stays and would activate if FALLBACK_API_KEY were ever set.
VERDICT_MODELS = ["gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite"]
VERDICTS = ["met", "missed", "partly", "on track", "behind", "pending", "can't tell"]
PROMPT_VERSION = "v1"

# metric name (from M5, free text) -> thread key, by keyword rules
THREAD_RULES = [
    (["gross margin"], "Gross margin"),
    (["margin impact", "margin benefit", "margin headwind", "margin drag", "bps impact"], "Margin impact (one-off)"),
    (["margin"], "Operating margin"),
    (["volume"], "Volume growth"),
    (["order book", "tcv", "deal win", "deal"], "Order book (TCV)"),
    (["dividend", "payout", "buyback", "capital return"], "Capital return"),
    (["net debt", "debt", "leverage", "borrowing"], "Net debt"),
    (["capex", "capacity", "capital expenditure", "investment", "data center", "data centre", "plant"], "Capex / capacity"),
    (["price", "pricing"], "Pricing"),
    (["headcount", "employee", "people", "hiring", "engineer", "attrition"], "People"),
    (["revenue", "growth", "demand", "sales", "topline", "top-line"], "Revenue growth"),
    (["pat", "net profit", "profit"], "Net profit"),
]
SCREENER_METRICS = {"Revenue growth": "YoY Sales growth", "Net profit": "Net Profit"}   # definitions that match screener
# metrics whose actual means little without a company definition: never ask screener
MONTHS_END = {3: 31, 6: 30, 9: 30, 12: 31}

ACTUALS_PROMPT = """You are reading the transcript of {company}'s earnings conference call for {quarter}{held}.
Pages are marked "[page N]".

For each metric below, find the ACTUAL figure that management REPORTED for the quarter just ended
(and for the full financial year if this is a Q4 call). Only figures stated by the company's own
management (CEO, MD, CFO, business heads), not analysts' numbers, not targets or guidance.
Metrics: {metrics}

Rules:
- Use the company's own definition (e.g. TCS "operating margin" = EBIT margin as the CFO states it).
- If a metric is not reported in this transcript, leave it out.
- "quote" must be VERBATIM from the transcript (at most 2 sentences, no paraphrase), with its [page N].

Return JSON:
{{"actuals": [
  {{"metric": "one of the metric names above, exactly",
   "value_text": "as stated, e.g. '25.2%', 'US$10 billion', 'volume growth of 7%'",
   "value_low": number or null, "value_high": number or null, "unit": "% | bps | Rs crore | USD bn | USD mn | x | count",
   "period": "Q2 FY27 | FY26 | H1 FY27",
   "quote": "verbatim sentence(s)", "page": N, "speaker": "Name, Role"}}
]}}

Transcript:
{transcript}
"""

VERDICT_PROMPT = """You are an equity analyst's assistant judging whether {company}'s management delivered on its own guidance.
Metric: {metric}

PROMISES (what management said, oldest first):
{promises}

TARGET MOVEMENT (computed): {movement}

EVIDENCE (what was actually reported later; each with its source):
{evidence}

ARITHMETIC (computed in Python, trust the numbers): {comparison}

THE VERDICT IS ALREADY DECIDED BY THE ARITHMETIC: "{final_verdict}". Do not change it.
Write ONE sentence (max 45 words) that explains that verdict, citing the promise (call quarter and page)
AND the evidence (call quarter and page, or the screener table and column), with the numbers. If the
target moved, say so. Cite only numbers that appear in PROMISES or EVIDENCE above. The sentence must
agree with the verdict "{final_verdict}" (for "can't tell" or "pending", say why it cannot be judged yet).

Return JSON: {{"verdict": "{final_verdict}", "sentence": "..."}}
"""


# ---------- threads ----------

SEGMENT_WORDS = ["catering", "tourism", "ticketing", "internet", "rail neer", "segment", "division", "vertical",
                 "international", "overseas", "domestic", "export", "subsidiary", "retail", "wholesale", "b2b", "b2c",
                 "decorative", "industrial", "lighting", "cables", "wires", "e-auction", "fsa", "bfsi", "hospital",
                 "pharmacy", "diagnostic", "online", "offline", "stores", "store", "franchise", "lounge"]


def segment_of(metric, target_text, quote):
    """A segment word in the metric, target or quote means the promise is about a part of the
    company (IRCTC's catering 15%, tourism 20%), never comparable with company-level numbers."""
    text = ((metric or "") + " " + (target_text or "") + " " + (quote or "")).lower()
    for w in SEGMENT_WORDS:
        if re.search(r"\b" + re.escape(w) + r"\b", text):
            return w
    return None


def thread_key(metric, target_text=None, quote=None):
    low = (metric or "").lower()
    target = (target_text or "").lower()
    # "150-200 bps impact on margin" is a one-off headwind, not the margin target itself
    if "margin" in low and any(w in target for w in ("impact", "headwind", "drag", "hit", "benefit", "tailwind")):
        return "Margin impact (one-off)"
    base = None
    for words, key in THREAD_RULES:
        for w in words:
            if w in low:
                base = key
                break
        if base:
            break
    if base is None:
        base = (metric or "Other").strip()
    segment = segment_of(metric, target_text, quote)
    if segment and base not in ("Capex / capacity", "People", "Net debt", "Capital return", "Pricing"):
        return base + " · " + segment          # its own thread, no screener comparison
    return base


def period_end(period, call_quarter_end):
    """'FY27' -> 2027-03-31 ; 'H1 FY27' -> 2026-09-30 ; 'Q3 FY27' -> 2026-12-31 ;
    'next quarter' -> the quarter after the call's ; open-ended ('medium term') -> None."""
    text = (period or "").lower().replace("’", "'")
    m = re.search(r"(h1|h2|q1|q2|q3|q4)?\s*fy\s*'?(\d{2,4})", text)
    if m:
        fy = int(m.group(2))
        fy = fy + 2000 if fy < 100 else fy
        part = m.group(1)
        if part == "q1" or part == "h1":
            return date(fy - 1, 9, 30) if part == "h1" else date(fy - 1, 6, 30)
        if part == "q2":
            return date(fy - 1, 9, 30)
        if part == "q3":
            return date(fy - 1, 12, 31)
        return date(fy, 3, 31)          # q4, h2, or the whole FY
    if "next quarter" in text or "coming quarter" in text:
        return quarter_end_of(call_quarter_end + timedelta(days=1))      # the quarter after the call's
    m = re.search(r"(20\d\d)", text)
    if m and "year" not in text:
        return date(int(m.group(1)), 3, 31)
    return None     # medium term, next few quarters, next 2-3 years, ...


def norm_unit(unit):
    """'basis points' -> 'bps', 'Rs. crores' -> 'rs crore', 'US$ billion' -> 'usd bn', 'MT' -> 'count'..."""
    u = (unit or "").lower().replace(".", "").strip()
    if u in ("%", "percent", "percentage", "pct") or "%" in u:
        return "%"
    if "bps" in u or "basis" in u:
        return "bps"
    if "crore" in u or "cr" == u or "inr" in u or "rs" in u:
        return "rs crore"
    if ("usd" in u or "$" in u or "us" in u) and ("bn" in u or "billion" in u):
        return "usd bn"
    if ("usd" in u or "$" in u or "us" in u) and ("mn" in u or "million" in u):
        return "usd mn"
    if u in ("x", "times"):
        return "x"
    if u in ("count", "number", "mt", "kt", "tonnes", "tons", "units", "people", "employees", "stores"):
        return "count"
    return "text"


NUMERIC_UNITS = ("%", "bps", "rs crore", "usd bn", "usd mn", "x")


def period_bounds(period, call_quarter_end):
    """(start, end) dates of a target's own period: FY27 = 1 Apr 2026 .. 31 Mar 2027,
    H1 FY27 = Apr..Sep 2026, H2 FY27 = Oct 2026..Mar 2027, Q3 FY27 = Oct..Dec 2026,
    'next quarter' = the quarter after the call. Open-ended ('medium term') -> (None, None)."""
    end = period_end(period, call_quarter_end)
    if end is None:
        return None, None
    text = (period or "").lower()
    m = re.search(r"(h1|h2|q1|q2|q3|q4)?\s*fy\s*'?(\d{2,4})", text)
    if m:
        fy = int(m.group(2))
        fy = fy + 2000 if fy < 100 else fy
        part = m.group(1)
        if part is None:
            return date(fy - 1, 4, 1), end
        if part == "h1":
            return date(fy - 1, 4, 1), end
        if part == "h2":
            return date(fy - 1, 10, 1), end
        quarter_starts = {"q1": date(fy - 1, 4, 1), "q2": date(fy - 1, 7, 1), "q3": date(fy - 1, 10, 1), "q4": date(fy, 1, 1)}
        return quarter_starts[part], end
    # "next quarter": the quarter that ends at `end` starts two months earlier
    start_month = end.month - 2
    start_year = end.year
    if start_month <= 0:
        start_month = start_month + 12
        start_year = start_year - 1
    return date(start_year, start_month, 1), end


def movement_between(a, b):
    """How the target changed from promise a to the later promise b (same thread).
    Numbers are compared only when both targets are in the same numeric unit; otherwise
    only the wording can be compared ('changed' / 'reiterated')."""
    def num(x):
        try:
            return float(x) if x is not None else None
        except (TypeError, ValueError):
            return None
    al, ah, bl, bh = num(a.get("target_low")), num(a.get("target_high")), num(b.get("target_low")), num(b.get("target_high"))
    same_unit = norm_unit(a.get("unit")) == norm_unit(b.get("unit")) and norm_unit(a.get("unit")) in NUMERIC_UNITS
    if same_unit and (al is not None or ah is not None) and (bl is not None or bh is not None):
        a_mid = (al if al is not None else ah) if ah is None or al is None else (al + ah) / 2
        b_mid = (bl if bl is not None else bh) if bh is None or bl is None else (bl + bh) / 2
        if abs(a_mid - b_mid) < 1e-9 and (al == bl) and (ah == bh):
            return "reiterated"
        return "raised" if b_mid > a_mid else "lowered"
    ta = " ".join(str(a.get("target_text", "")).lower().split())
    tb = " ".join(str(b.get("target_text", "")).lower().split())
    return "reiterated" if ta == tb else "changed"


def build_threads(items, transcripts):
    """Group M5 promises by thread key; add period_end/period_over and the target movement."""
    latest_quarter_end = max(datetime.strptime(t["quarter_end"], "%Y-%m-%d").date() for t in transcripts)
    newest_call = max(transcripts, key=lambda t: t["quarter_end"])["quarter"]
    quarter_ends = {t["quarter"]: datetime.strptime(t["quarter_end"], "%Y-%m-%d").date() for t in transcripts}
    threads = {}
    for item in items:
        key = thread_key(item.get("metric"), item.get("target_text"), item.get("quote"))
        call_end = quarter_ends.get(item["call_quarter"], latest_quarter_end)
        end = period_end(item.get("period"), call_end)
        promise = dict(item)
        promise["thread_key"] = key
        promise["period_end"] = end.isoformat() if end else None
        promise["period_over"] = bool(end and end <= latest_quarter_end)
        promise["open_ended"] = end is None
        threads.setdefault(key, []).append(promise)

    result = []
    for key in threads:
        promises = sorted(threads[key], key=lambda p: quarter_ends.get(p["call_quarter"], date.min))
        # target movement call to call: compare each promise with the previous call's promise
        # in the same unit (two statements on the same call are not a "movement")
        movement = []
        for i in range(1, len(promises)):
            current = promises[i]
            previous = None
            for j in range(i - 1, -1, -1):
                if promises[j]["call_quarter"] != current["call_quarter"] and norm_unit(promises[j].get("unit")) == norm_unit(current.get("unit")):
                    previous = promises[j]
                    break
            if previous is None:
                continue
            movement.append({"from_quarter": previous["call_quarter"], "to_quarter": current["call_quarter"],
                             "from": previous.get("target_text"), "to": current.get("target_text"),
                             "change": movement_between(previous, current)})
        mentioned_quarters = sorted(set(p["call_quarter"] for p in promises), key=lambda q: quarter_ends.get(q, date.min))
        dropped = newest_call not in mentioned_quarters and len(promises) >= 2
        result.append({"key": key, "metric": key, "promises": promises, "movement": movement,
                       "dropped": dropped, "newest_call": newest_call, "latest_quarter_end": latest_quarter_end.isoformat()})
    return result


# ---------- actuals from later transcripts (cheap model, verified quotes) ----------

def actuals_cache_path(url, metrics):
    key = url + "|" + "|".join(sorted(metrics)) + "|" + PROMPT_VERSION
    return os.path.join(PROMISES_CACHE_DIR, "actuals_" + hashlib.sha1(key.encode("utf-8")).hexdigest() + ".json")


def actuals_from_transcript(company_name, transcript, metrics):
    """Reported figures for the given thread metrics in one transcript. Quotes verified; cached."""
    os.makedirs(PROMISES_CACHE_DIR, exist_ok=True)
    path = actuals_cache_path(transcript["url"], metrics)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    pages = get_pages(transcript["url"])
    labelled = []
    for i, page in enumerate(pages):
        labelled.append("[page " + str(i + 1) + "]\n" + page)
    held = (" held on " + transcript["call_date"]) if transcript.get("call_date") else ""
    prompt = ACTUALS_PROMPT.format(company=company_name, quarter=transcript["quarter"], held=held,
                                   metrics="; ".join(metrics), transcript="\n".join(labelled))
    answer = call_llm(prompt, json_output=True, purpose="actuals", temperature=0)
    try:
        raw = json.loads(answer)
        raw_items = raw.get("actuals", []) if isinstance(raw, dict) else raw
    except ValueError:
        raw_items = []
    actuals = []
    dropped = 0
    for item in raw_items or []:
        if not isinstance(item, dict):
            continue
        try:
            page = int(item.get("page") or 0)
        except (TypeError, ValueError):
            page = 0
        real_page = find_quote(str(item.get("quote", "")), pages, page)
        if real_page is None:
            dropped = dropped + 1
            continue
        actuals.append({"metric": thread_key(item.get("metric"), None, item.get("quote")), "metric_as_named": item.get("metric"),
                        "value_text": item.get("value_text"), "value_low": item.get("value_low"), "value_high": item.get("value_high"),
                        "unit": item.get("unit"), "period": item.get("period"), "quote": item.get("quote"), "page": real_page,
                        "speaker": item.get("speaker"), "call_quarter": transcript["quarter"], "call_date": transcript.get("call_date"),
                        "url": transcript["url"], "source": "transcript"})
    result = {"quarter": transcript["quarter"], "extracted": len(raw_items or []), "verified": len(actuals), "dropped": dropped, "actuals": actuals}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=1)
    return result


FORWARD_WORDS = re.compile(r"\b(will|would|should|shall|expect(s|ed|ing)?|estimat(e|ed|es|ing)|target(s|ed|ing)?|plan(s|ned|ning)?|"
                           r"guidance|guid(e|ed|ing)|outlook|aim(s|ing)?|intend(s|ed)?|likely|going to|coming (year|quarter)|next (year|quarter)|"
                           r"by (fy|march|end))\b", re.I)
INVESTMENT_WORDS = re.compile(r"\b(invest(ment|ments|ed)? in|stake|acqui(re|red|sition)|equity|minority|jv|joint venture)\b", re.I)
CAPEX_WORDS = re.compile(r"\b(capex|capital expenditure|capacity|plant|line|expansion)\b", re.I)


def actual_is_usable(actual, call_quarter_end, promise_quotes):
    """Python's filter on a reported figure. Returns (ok, reason)."""
    quote = " ".join(str(actual.get("quote") or "").split()).lower()
    # 1. its period must have ended by the call (an FY27 figure given on a Q2 FY27 call is a forecast)
    end = period_end(actual.get("period"), call_quarter_end)
    if end is not None and end > call_quarter_end:
        return False, "period " + str(actual.get("period")) + " had not ended at that call"
    # 2. not a promise quoted back as an actual
    for pq in promise_quotes:
        if pq and (pq in quote or quote in pq):
            return False, "repeats a promise quote"
    # 3. not forward-looking wording
    m = FORWARD_WORDS.search(quote)
    if m:
        return False, "forward-looking wording ('" + m.group(0) + "')"
    # 4. an investment or stake is not capex
    if actual.get("metric", "").startswith("Capex") and INVESTMENT_WORDS.search(quote) and not CAPEX_WORDS.search(quote):
        return False, "an investment, not capex"
    return True, ""


# ---------- actuals from screener (only matching definitions) ----------

def screener_growth(company, key):
    """Quarterly YoY growth (and FY growth) for revenue or PAT, as evidence rows."""
    rows = []
    q = company["quarters"]
    pl = company["profit_loss"]
    if key == "Revenue growth":
        row = "YoY Sales growth" if "YoY Sales growth" in q["rows"] else "YoY Revenue growth"
        for i, col in enumerate(q["columns"]):
            v = q["rows"].get(row, [None] * len(q["columns"]))[i]
            if v is not None:
                rows.append({"source": "screener", "table": "quarters", "row": row, "column": col, "value": v, "unit": "%",
                             "period_end": column_end(col)})
        row = "Sales growth" if "Sales growth" in pl["rows"] else "Revenue growth"
        for i, col in enumerate(pl["columns"]):
            if col == "TTM":
                continue
            v = pl["rows"].get(row, [None] * len(pl["columns"]))[i]
            if v is not None:
                rows.append({"source": "screener", "table": "profit_loss", "row": row, "column": col, "value": v, "unit": "%",
                             "period_end": column_end(col), "fiscal_year": True})
    if key == "Net profit":
        values = q["rows"].get("Net Profit", [])
        for i in range(4, len(values)):
            if values[i] is not None and values[i - 4]:
                rows.append({"source": "screener", "table": "quarters", "row": "Net Profit YoY (computed)", "column": q["columns"][i],
                             "value": round((values[i] - values[i - 4]) / abs(values[i - 4]) * 100, 1), "unit": "%",
                             "period_end": column_end(q["columns"][i])})
    return rows


def column_end(col):
    """'Sep 2026' -> 2026-09-30."""
    try:
        d = datetime.strptime(col, "%b %Y").date()
        return date(d.year, d.month, MONTHS_END.get(d.month, 30)).isoformat()
    except ValueError:
        return None


# ---------- comparison (Python) ----------

def to_float(x):
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None


def is_fiscal_year_period(period):
    """'FY27' yes; 'H2 FY27', 'Q3 FY27', 'next quarter', 'medium term' no."""
    text = (period or "").lower().strip()
    return bool(re.fullmatch(r"fy\s*'?\d{2,4}", text))


def fallback_sentence(thread):
    """A plain sentence from the arithmetic when the model's answer is unusable."""
    with_evidence = [p for p in thread["promises"] if p["comparison"]["used"]]
    p = (with_evidence or thread["promises"])[-1]
    text = ("Promise (" + p["call_quarter"] + ", p." + str(p["page"]) + "): " + str(p.get("target_text")) + " for "
            + str(p.get("period")) + "; " + p["comparison"]["detail"])
    used = p["comparison"]["used"]
    if used:
        e = used[-1]
        if e.get("source") == "transcript":
            text = text + " (evidence: " + e["call_quarter"] + ", p." + str(e["page"]) + ", " + str(e.get("value_text")) + ")"
        else:
            text = text + " (evidence: screener " + e["table"] + " / " + e["row"] + " / " + e["column"] + " = " + str(e["value"]) + ")"
    return text + "."


def compare(promise, evidence):
    """Arithmetic verdict for one promise against the evidence rows that fall after its call.
    Returns {"python_verdict", "detail", "used": [...]}"""
    low, high = to_float(promise.get("target_low")), to_float(promise.get("target_high"))
    direction = (promise.get("direction") or "").lower()
    over = promise["period_over"]
    if promise.get("thread_key") == "Margin impact (one-off)":
        # a guided headwind that turns out smaller is good news, a benefit that turns out smaller is bad:
        # the sign is not in the numbers, so one-off impacts are reported but never scored
        return {"python_verdict": "can't tell", "detail": "one-off margin impacts are listed, not scored (a smaller headwind is good, a smaller benefit is bad)", "used": []}
    end = promise.get("period_end")
    call_end = promise.get("call_quarter_end")
    target_unit = norm_unit(promise.get("unit"))
    # evidence after the call AND inside the target's own period: an FY27 target is judged
    # only on FY27 quarters or the FY27 annual figure, never on FY26's; a period that has
    # not started yet is pending; an open-ended target may use anything after the call
    start, _ = period_bounds(promise.get("period"), datetime.strptime(call_end, "%Y-%m-%d").date()) if call_end else (None, None)
    start_iso = start.isoformat() if start else None
    later = []
    for e in evidence:
        e_end = e.get("period_end")
        if e_end is None or call_end is None or e_end <= call_end:
            continue
        if end is not None and e_end > end:
            continue
        if start_iso is not None and e_end < start_iso:
            continue
        later.append(e)
    later.sort(key=lambda e: e.get("period_end") or "")
    if not later:
        latest_known = max((e.get("period_end") or "" for e in evidence), default="")
        if start_iso is not None and latest_known and latest_known < start_iso:
            return {"python_verdict": "pending", "detail": "period " + str(promise.get("period")) + " has not started yet (starts " + start_iso + ")", "used": []}
        return {"python_verdict": "pending", "detail": "no evidence inside the period yet" + (" (period over)" if over else ""), "used": []}

    # only evidence in the same unit can be compared; a target without a measurable unit can't be judged
    if target_unit not in NUMERIC_UNITS and target_unit != "count":
        return {"python_verdict": "can't tell", "detail": "target has no measurable unit (" + str(promise.get("unit")) + ")", "used": later[-3:]}
    used = [e for e in later if norm_unit(e.get("unit")) == target_unit]
    if not used:
        return {"python_verdict": "can't tell", "detail": "later evidence exists but in a different unit than the target ("
                + str(promise.get("unit")) + ")", "used": later[-3:]}
    # a full-year target is judged on full-year figures when the transcripts report them
    # (quarterly TCV can't be compared with an FY TCV target); otherwise the quarters inside the period count
    if is_fiscal_year_period(promise.get("period")):
        fy_rows = [e for e in used if e.get("fiscal_year") or str(e.get("period", "")).upper().startswith("FY")]
        if fy_rows:
            used = fy_rows
    elif not promise.get("open_ended"):
        used = [e for e in used if not (e.get("fiscal_year") or str(e.get("period", "")).upper().startswith("FY"))] or used

    values = [to_float(e.get("value")) for e in used if to_float(e.get("value")) is not None]
    if low is None and high is None:
        # direction-only or text target: compare the first and last later actuals
        if direction in ("up", "down") and len(values) >= 2:
            moved = values[-1] - values[0]
            good = moved > 0 if direction == "up" else moved < 0
            v = ("met" if good else "missed") if over else ("on track" if good else "behind")
            return {"python_verdict": v, "detail": "direction " + direction + ": " + str(values[0]) + " -> " + str(values[-1]), "used": used}
        return {"python_verdict": "can't tell", "detail": "target has no number to compare", "used": used}
    if not values:
        return {"python_verdict": "can't tell", "detail": "evidence has no number", "used": used}

    latest = values[-1]
    if low is not None and high is not None:
        inside = low <= latest <= high
        above = latest > high
        good = inside or (above and direction != "down")
        where = "inside" if inside else ("above" if above else "below")
    elif low is not None:          # "25%+" / "at least"
        good = latest >= low
        where = "at or above" if good else "below"
    else:                          # "not more than"
        good = latest <= high
        where = "at or below" if good else "above"
    # all later actuals, for "partly"
    all_good = True
    for v in values:
        if low is not None and v < low - 1e-9:
            all_good = False
        if high is not None and v > high + 1e-9 and direction == "down":
            all_good = False
    if over:
        verdict = "met" if good and all_good else ("partly" if good or (len(values) > 1 and any(low is not None and v >= low for v in values)) else "missed")
    else:
        verdict = "on track" if good else "behind"
    target = str(promise.get("target_text"))
    return {"python_verdict": verdict, "detail": "latest actual " + str(latest) + " is " + where + " the target " + target
            + " (" + str(len(values)) + " later data point(s); period " + ("over" if over else "not over") + ")", "used": used}


# ---------- the verdict (stronger model) ----------

VERDICT_VERSION = "v3"     # v2: Python's verdict is final; v3: evidence must lie inside the target's period


def verdict_cache_path(ticker, key):
    return os.path.join(PROMISES_CACHE_DIR, "verdict_" + hashlib.sha1((ticker + "|" + key + "|" + VERDICT_VERSION).encode("utf-8")).hexdigest() + ".json")


def write_verdict(company_name, thread):
    prompt = verdict_prompt(company_name, thread)
    answer = call_llm(prompt, json_output=True, purpose="verdict", temperature=0, models=VERDICT_MODELS)
    model = answer_model(prompt, models=VERDICT_MODELS)
    try:
        data = json.loads(answer)
        verdict = str(data.get("verdict", "")).lower().strip()
        sentence = str(data.get("sentence", "")).strip()
    except (ValueError, AttributeError):
        verdict, sentence = "", ""
    # Python's verdict is final; the model only writes the sentence, and it must not contradict it
    verdict = thread["python_verdict"]
    if thread["key"] == "Margin impact (one-off)":
        verdict = "can't tell"
    if verdict == "missed" and not any(p["period_over"] for p in thread["promises"]):
        verdict = "behind"
    if not sentence or sentence_contradicts(sentence, verdict):
        sentence = fallback_sentence(thread)
    return verdict, sentence, model


CONTRADICTION_WORDS = {
    "met": ["missed", "behind", "not met", "fell short"],
    "on track": ["missed", "behind", "fell short", "lagging"],
    "partly": ["fully met", "exceeded"],
    "missed": ["met", "on track", "achieved", "exceeded"],
    "behind": ["on track", "met the", "achieved", "exceeded", "ahead"],
    "pending": ["met", "missed", "on track", "behind", "achieved"],
    "can't tell": ["met", "missed", "on track", "behind", "achieved", "exceeded"],
}


def sentence_contradicts(sentence, verdict):
    low = " " + sentence.lower() + " "
    for w in CONTRADICTION_WORDS.get(verdict, []):
        if " " + w + " " in low or " " + w + "," in low or " " + w + "." in low:
            return True
    return False


def verdict_prompt(company_name, thread):
    """The exact prompt the verdict model sees (also used to find its cache entry)."""
    promises_text = []
    for p in thread["promises"]:
        promises_text.append("- " + p["call_quarter"] + " (page " + str(p["page"]) + ", " + str(p.get("speaker")) + "): target "
                             + str(p.get("target_text")) + " for " + str(p.get("period")) + " [period end " + str(p.get("period_end") or "open-ended")
                             + ", period over: " + str(p["period_over"]) + "]. Quote: \"" + str(p.get("quote")) + "\"")
    # give the model only the evidence rows the arithmetic actually used (fewer numbers to misquote)
    rows = []
    for p in thread["promises"]:
        for e in p["comparison"]["used"]:
            if e not in rows:
                rows.append(e)
    if not rows:
        rows = thread["evidence"][-4:]
    evidence_text = []
    for e in rows:
        if e.get("source") == "transcript":
            evidence_text.append("- " + e["call_quarter"] + " call, page " + str(e["page"]) + " (" + str(e.get("speaker")) + "): "
                                 + str(e.get("value_text")) + " for " + str(e.get("period")) + ". Quote: \"" + str(e.get("quote")) + "\"")
        else:
            evidence_text.append("- screener " + e["table"] + " / " + e["row"] + " / " + e["column"] + ": " + str(e["value"]) + str(e.get("unit", "")))
    if not evidence_text:
        evidence_text.append("- none yet")
    movement = "; ".join(m["from_quarter"] + " -> " + m["to_quarter"] + ": " + m["change"] + " (" + str(m["from"]) + " -> " + str(m["to"]) + ")"
                         for m in thread["movement"]) or "single mention"
    if thread["dropped"]:
        movement = movement + "; NOT mentioned on the newest call (" + thread["newest_call"] + ")"
    comparison = "; ".join(p["call_quarter"] + " promise: " + p["comparison"]["python_verdict"] + " - " + p["comparison"]["detail"]
                           for p in thread["promises"])
    final = thread["python_verdict"]
    if thread["key"] == "Margin impact (one-off)":
        final = "can't tell"
    if final == "missed" and not any(p["period_over"] for p in thread["promises"]):
        final = "behind"
    return VERDICT_PROMPT.format(company=company_name, metric=thread["metric"], promises="\n".join(promises_text),
                                 movement=movement, evidence="\n".join(evidence_text), comparison=comparison, final_verdict=final)


def thread_python_verdict(thread):
    """One arithmetic verdict for the thread: the newest promise with evidence decides; else the newest."""
    ranked = {"missed": 6, "behind": 5, "partly": 4, "met": 3, "on track": 2, "can't tell": 1, "pending": 0}
    with_evidence = [p for p in thread["promises"] if p["comparison"]["used"]]
    pick = with_evidence if with_evidence else thread["promises"]
    newest = pick[-1]
    v = newest["comparison"]["python_verdict"]
    # if any finished promise in the thread was missed, that matters more than a newer "pending"
    for p in thread["promises"]:
        if p["period_over"] and p["comparison"]["python_verdict"] in ("missed", "partly") and ranked[p["comparison"]["python_verdict"]] > ranked.get(v, 0):
            v = p["comparison"]["python_verdict"]
    return v


# ---------- scorecard ----------

def credibility_line(threads):
    counts = {v: 0 for v in VERDICTS}
    for t in threads:
        counts[t["verdict"]] = counts[t["verdict"]] + 1
    decided = counts["met"] + counts["missed"] + counts["partly"]
    running = counts["on track"] + counts["behind"]
    lowered = sum(1 for t in threads for m in t["movement"] if m["change"] == "lowered")
    raised = sum(1 for t in threads for m in t["movement"] if m["change"] == "raised")
    dropped = sum(1 for t in threads if t["dropped"])
    good = counts["met"] + counts["on track"]
    bad = counts["missed"] + counts["behind"]
    parts = []
    if decided + running == 0:
        parts.append("Nothing checkable yet: every promise is pending or too loose to test")
    elif bad == 0 and good >= 2:
        parts.append("Guidance has held up: " + str(good) + " of " + str(decided + running) + " checkable threads met or on track")
    elif bad > good:
        parts.append("Guidance has run ahead of delivery: " + str(bad) + " of " + str(decided + running) + " checkable threads missed or behind")
    else:
        parts.append("Mixed record: " + str(good) + " met/on track, " + str(bad) + " missed/behind, " + str(counts["partly"]) + " partly")
    if lowered:
        parts.append(str(lowered) + " target" + ("s" if lowered > 1 else "") + " lowered along the way")
    if raised:
        parts.append(str(raised) + " raised")
    if dropped:
        parts.append(str(dropped) + " thread" + ("s" if dropped > 1 else "") + " no longer mentioned on the latest call")
    if counts["pending"]:
        parts.append(str(counts["pending"]) + " pending")
    return "; ".join(parts) + ".", counts


# ---------- put together ----------

def build_scorecard(ticker, use_cache=True):
    started = time.time()
    run_started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    guidance = extract_guidance(ticker)
    if guidance is None:
        return None
    company = get_company(ticker)
    transcripts = guidance["transcripts"]
    if not transcripts:
        # a company that holds no earnings calls (e.g. MRF): nothing to check, and that is the finding
        empty = {v: 0 for v in VERDICTS}
        return {"ticker": ticker.upper(), "name": guidance["name"], "threads": [],
                "scorecard": {"threads": 0, "promises": 0, "counts": empty,
                              "credibility": "No earnings-call transcripts in the last 15 months on screener or NSE, so there is no current management guidance to check."},
                "actual_extraction": [], "transcripts": [], "tokens_this_run": {}, "seconds": round(time.time() - started, 1), "built_on": run_started}
    quarter_ends = {t["quarter"]: t["quarter_end"] for t in transcripts}
    threads = build_threads(guidance["items"], transcripts)
    for t in threads:
        for p in t["promises"]:
            p["call_quarter_end"] = quarter_ends.get(p["call_quarter"])

    # actuals: company-defined metrics from every transcript (each later one is evidence for earlier promises)
    metric_names = sorted(set(t["key"] for t in threads if t["key"] not in SCREENER_METRICS))
    actual_stats = []
    evidence_by_key = {t["key"]: [] for t in threads}
    promise_quotes = [" ".join(str(p.get("quote") or "").split()).lower() for t in threads for p in t["promises"]]
    if metric_names:
        for transcript in sorted(transcripts, key=lambda x: x["quarter_end"]):
            result = actuals_from_transcript(guidance["name"], transcript, metric_names)
            call_end = datetime.strptime(transcript["quarter_end"], "%Y-%m-%d").date()
            filtered = []
            for a in result["actuals"]:
                if a["metric"] not in evidence_by_key:
                    continue
                ok, reason = actual_is_usable(a, call_end, promise_quotes)
                if not ok:
                    filtered.append({"metric": a["metric"], "value_text": a.get("value_text"), "page": a.get("page"), "reason": reason})
                    continue
                a["value"] = a.get("value_low") if a.get("value_low") is not None else a.get("value_high")
                a["period_end"] = quarter_ends.get(a["call_quarter"])      # reported on this call = the quarter just ended
                evidence_by_key[a["metric"]].append(a)
            actual_stats.append({"quarter": result["quarter"], "extracted": result["extracted"], "verified": result["verified"],
                                 "dropped": result["dropped"], "filtered_by_rules": filtered})
    # screener rows only from a year before the oldest call (older history is not evidence for these promises)
    oldest_call = min(t["quarter_end"] for t in transcripts)
    cutoff = (datetime.strptime(oldest_call, "%Y-%m-%d").date() - timedelta(days=400)).isoformat()
    for key in SCREENER_METRICS:
        if key in evidence_by_key and company is not None:
            for row in screener_growth(company, key):
                if row.get("period_end") and row["period_end"] >= cutoff:
                    evidence_by_key[key].append(row)

    # compare + verdict per thread
    for t in threads:
        t["evidence"] = sorted(evidence_by_key.get(t["key"], []), key=lambda e: e.get("period_end") or "")
        for p in t["promises"]:
            p["comparison"] = compare(p, t["evidence"])
        t["python_verdict"] = thread_python_verdict(t)
        path = verdict_cache_path(ticker, t["key"])
        if use_cache and os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                saved = json.load(f)
            t["verdict"], t["sentence"], t["verdict_model"] = saved["verdict"], saved["sentence"], saved.get("model")
        else:
            t["verdict"], t["sentence"], t["verdict_model"] = write_verdict(guidance["name"], t)
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"verdict": t["verdict"], "sentence": t["sentence"], "model": t["verdict_model"]}, f, indent=1)

    line, counts = credibility_line(threads)
    tokens = {}
    for purpose in ("guidance", "actuals", "verdict"):
        calls, inputs, outputs, cached = tokens_since(run_started, purpose)
        tokens[purpose] = {"calls": calls, "input": inputs, "output": outputs, "cache_hits": cached}
    result = {"ticker": ticker.upper(), "name": guidance["name"], "threads": threads,
              "scorecard": {"threads": len(threads), "promises": len(guidance["items"]), "counts": counts, "credibility": line},
              "actual_extraction": actual_stats, "transcripts": [t["quarter"] for t in transcripts],
              "tokens_this_run": tokens, "seconds": round(time.time() - started, 1), "built_on": run_started}
    os.makedirs(PROMISES_CACHE_DIR, exist_ok=True)
    with open(os.path.join(PROMISES_CACHE_DIR, ticker.upper() + ".json"), "w", encoding="utf-8") as f:
        json.dump(result, f, indent=1, ensure_ascii=False, default=str)
    return result


def tokens_since(since, purpose):
    calls = inputs = outputs = cached = 0
    if not os.path.exists(COST_LOG_PATH):
        return calls, inputs, outputs, cached
    with open(COST_LOG_PATH, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["purpose"] != purpose or row["time"] < since:
                continue
            if row["model"] == "cache":
                cached = cached + 1
                continue
            calls = calls + 1
            inputs = inputs + int(row["input_tokens"])
            outputs = outputs + int(row["output_tokens"])
    return calls, inputs, outputs, cached


def print_scorecard(result):
    print("\n==========", result["ticker"], "|", result["name"], "| calls:", ", ".join(result["transcripts"]), "==========")
    for t in result["threads"]:
        print("\n## " + t["metric"] + "  ->  " + t["verdict"].upper() + "  (arithmetic: " + t["python_verdict"] + "; model: " + str(t["verdict_model"]) + ")")
        for p in t["promises"]:
            print("   promise ", p["call_quarter"], "p." + str(p["page"]), "|", str(p.get("target_text"))[:40], "|", str(p.get("period")),
                  "| period end", p.get("period_end") or "open", "| over:", p["period_over"], "->", p["comparison"]["python_verdict"])
        for m in t["movement"]:
            print("   movement", m["from_quarter"], "->", m["to_quarter"], ":", m["change"].upper(), "(" + str(m["from"]) + " -> " + str(m["to"]) + ")")
        if t["dropped"]:
            print("   movement: not mentioned on the newest call (" + t["newest_call"] + ")")
        for e in t["evidence"]:
            if e.get("source") == "transcript":
                print("   evidence", e["call_quarter"], "p." + str(e["page"]), "|", str(e.get("value_text"))[:50], "|", str(e.get("period")))
            else:
                print("   evidence screener", e["table"] + "/" + e["row"] + "/" + e["column"], "=", e["value"], e.get("unit", ""))
        print("   >>", t["sentence"])
    s = result["scorecard"]
    print("\nSCORECARD:", s["promises"], "promises in", s["threads"], "threads ->", {k: v for k, v in s["counts"].items() if v})
    print("CREDIBILITY:", s["credibility"])
    print("actual extraction per transcript:", result["actual_extraction"])
    print("tokens this run:", result["tokens_this_run"], "| took", result["seconds"], "s")


if __name__ == "__main__":
    for symbol in sys.argv[1:] or ["TCS"]:
        result = build_scorecard(symbol)
        if result is None:
            print("\n", symbol, "-> not found on screener")
            continue
        print_scorecard(result)
