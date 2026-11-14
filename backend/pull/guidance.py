"""Management guidance ("promises") from the last 5 concall transcripts, with verified quotes.

extract_guidance("TCS") ->
  {"ticker", "items": [promise...], "stats": {...}, "transcripts": [...]}
promise = {"call_quarter", "call_date", "metric", "target_text", "target_low", "target_high", "unit",
           "direction", "period", "quote", "page", "speaker", "speaker_in_transcript", "url"}

How it works:
  1. pull/docs.get_transcripts(ticker, n=5): the 5 most recent calls (the oldest ones hold the
     promises that the later quarters can be checked against; the newest call's are "pending").
  2. One cheap-model call per transcript (temperature 0, JSON), pages labelled "[page N]".
     Only management's explicit, checkable forward guidance on headline items; max 8 per call.
  3. Python verifies every quote: it must appear on the cited page or a neighbouring page
     (case, whitespace, quote marks and ligatures normalised; the page is corrected if it
     was off by one). Anything unverified is DROPPED and counted. The check is never loosened.
  4. The verified result is cached per transcript (data/cache/guidance/), and the LLM answer
     itself is cached by llm.py, so a re-run costs nothing.

Usage:  python pull\\guidance.py TCS ASIANPAINT
"""
import csv
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from llm import COST_LOG_PATH, call_llm
from pull.docs import get_pages, get_transcripts

GUIDANCE_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "cache", "guidance")
PROMPT_VERSION = "v1"
TRANSCRIPTS = 5
MAX_ITEMS = 8

PROMPT = """You are reading the transcript of {company}'s earnings conference call for {quarter}{held}.
Pages are marked "[page N]".

Extract ONLY management's explicit forward-looking guidance and checkable growth commentary on
HEADLINE items: revenue or volume growth, margins (operating/EBITDA/EBIT), capex, debt or leverage,
order book / deal wins (TCV), dividends/buybacks, and the company's own key KPIs (e.g. AI revenue,
headcount, store or capacity additions, pricing actions).

Rules:
- Only statements by the company's own management (CEO, MD, CFO, COO, business heads). Never the
  moderator, never an analyst's question, never an analyst's number that management merely did not deny.
- Only forward-looking AND checkable later: a number, a range, or a clear direction with a time frame
  ("double-digit growth in FY27", "margins to improve 50-100 bps over the year", "capex of Rs 4,000 crore
  next year", "net debt to be zero by March"). Skip reported past results, generic confidence
  ("we remain optimistic"), industry or macro commentary, and anything without a period.
- At most {max_items} items, the most material first. If there is no such guidance, return an empty list.
- "quote" must be copied VERBATIM from the transcript (at most 2 sentences, no paraphrase, no "...").
- "page" is the [page N] number where the quote appears.

Return JSON:
{{"items": [
  {{"metric": "short name, e.g. Revenue growth / Operating margin / Capex / Net debt / Order book / AI revenue",
   "target_text": "the target as management put it, e.g. 'double-digit', '26-28%', 'Rs 4,000-4,500 crore', 'reduce'",
   "target_low": number or null, "target_high": number or null,
   "unit": "% | bps | Rs crore | USD mn | USD bn | x | count | text",
   "direction": "up | down | flat | null",
   "period": "FY27 | H2 FY27 | Q3 FY27 | next quarter | next 2-3 years | medium term",
   "quote": "verbatim sentence(s)",
   "page": N,
   "speaker": "Name, Role"}}
]}}

Transcript:
{transcript}
"""


# ---------- quote verification ----------

def normalise(text):
    """Lower-case, straight quotes, no ligatures, single spaces, no soft hyphens: for matching only."""
    text = text.replace("‘", "'").replace("’", "'").replace("“", '"').replace("”", '"')
    text = text.replace("ﬁ", "fi").replace("ﬂ", "fl").replace("ﬀ", "ff").replace("ﬃ", "ffi").replace("ﬄ", "ffl")
    # some PDF fonts map the "ff" ligature to U+01AF ("eƯorts" in a TCS transcript): a glyph glitch, not a different word
    text = text.replace("Ư", "ff").replace("ư", "ff")
    text = text.replace("­", "").replace("–", "-").replace("—", "-")
    text = text.replace("- ", "-")              # "domain- specific" (a line-break hyphen) -> "domain-specific"
    text = re.sub(r"[^a-z0-9%$.,'\"\-\s]", " ", text.lower())
    return " ".join(text.split())


def letters_only(text):
    """Even stricter normalisation: alphanumerics and spaces only (punctuation often differs)."""
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", normalise(text)).split())


def find_quote(quote, pages, page_number):
    """Return the 1-based page where the quote really is (cited page, then +-1, then the two
    pages joined for a quote that crosses a page break), or None."""
    if not quote or len(quote.strip()) < 15:
        return None
    candidates = []
    for p in (page_number, page_number - 1, page_number + 1):
        if p is not None and 1 <= p <= len(pages):
            candidates.append(p)
    q1 = normalise(quote)
    q2 = letters_only(quote)
    for p in candidates:
        text = pages[p - 1]
        if q1 in normalise(text) or q2 in letters_only(text):
            return p
    # across a page break: join each neighbouring pair
    for p in candidates:
        if p + 1 <= len(pages):
            joined = pages[p - 1] + " " + pages[p]
            if q1 in normalise(joined) or q2 in letters_only(joined):
                return p
    return None


def speaker_in_transcript(speaker, pages):
    """Is the speaker's surname somewhere in the transcript? (a cheap guard against invented names)"""
    if not speaker:
        return False
    name = speaker.split(",")[0]
    words = [w for w in re.findall(r"[A-Za-z]+", name) if len(w) > 2 and w.lower() not in ("mr", "mrs", "ms", "dr")]
    if not words:
        return False
    full = normalise(" ".join(pages))
    return words[-1].lower() in full


# ---------- one transcript ----------

def cache_path(url):
    return os.path.join(GUIDANCE_CACHE_DIR, hashlib.sha1((url + "|" + PROMPT_VERSION).encode("utf-8")).hexdigest() + ".json")


def guidance_for_transcript(company_name, transcript, use_cache=True):
    """Verified promises from one transcript, plus counts. Cached."""
    os.makedirs(GUIDANCE_CACHE_DIR, exist_ok=True)
    path = cache_path(transcript["url"])
    if use_cache and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    pages = get_pages(transcript["url"])
    labelled = []
    for i, page in enumerate(pages):
        labelled.append("[page " + str(i + 1) + "]\n" + page)
    held = (" held on " + transcript["call_date"]) if transcript.get("call_date") else ""
    prompt = PROMPT.format(company=company_name, quarter=transcript["quarter"], held=held,
                           max_items=MAX_ITEMS, transcript="\n".join(labelled))
    answer = call_llm(prompt, json_output=True, purpose="guidance", temperature=0)
    try:
        raw = json.loads(answer)
        if isinstance(raw, list):
            raw = {"items": raw}
        raw_items = raw.get("items", []) or []
    except (ValueError, AttributeError):
        raw_items = []

    items = []
    dropped = []
    for item in raw_items[:MAX_ITEMS]:
        if not isinstance(item, dict):
            continue
        try:
            page = int(item.get("page") or 0)
        except (TypeError, ValueError):
            page = 0
        real_page = find_quote(str(item.get("quote", "")), pages, page)
        if real_page is None:
            dropped.append({"metric": item.get("metric"), "quote": item.get("quote"), "page": page})
            continue
        items.append({
            "call_quarter": transcript["quarter"], "call_date": transcript.get("call_date"),
            "metric": item.get("metric"), "target_text": item.get("target_text"),
            "target_low": item.get("target_low"), "target_high": item.get("target_high"),
            "unit": item.get("unit"), "direction": item.get("direction"), "period": item.get("period"),
            "quote": item.get("quote"), "page": real_page, "page_as_cited": page,
            "speaker": item.get("speaker"), "speaker_in_transcript": speaker_in_transcript(item.get("speaker"), pages),
            "url": transcript["url"],
        })
    result = {"quarter": transcript["quarter"], "url": transcript["url"], "n_pages": len(pages),
              "extracted": len(raw_items), "verified": len(items), "dropped": dropped, "items": items,
              "checked_on": datetime.now().strftime("%Y-%m-%d %H:%M")}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=1)
    return result


# ---------- whole company ----------

def extract_guidance(ticker, n=TRANSCRIPTS, use_cache=True):
    docs = get_transcripts(ticker, n=n)
    if docs is None:
        return None
    all_items = []
    per_transcript = []
    extracted = 0
    verified = 0
    for transcript in docs["transcripts"]:
        started = time.time()
        result = guidance_for_transcript(docs["name"], transcript, use_cache)
        all_items.extend(result["items"])
        extracted = extracted + result["extracted"]
        verified = verified + result["verified"]
        per_transcript.append({"quarter": result["quarter"], "pages": result["n_pages"], "extracted": result["extracted"],
                               "verified": result["verified"], "dropped": len(result["dropped"]),
                               "seconds": round(time.time() - started, 1)})
    dropped = extracted - verified
    stats = {"transcripts": len(docs["transcripts"]), "extracted": extracted, "verified": verified, "dropped": dropped,
             "verified_pct": round(100.0 * verified / extracted, 1) if extracted else None, "per_transcript": per_transcript}
    return {"ticker": ticker.upper(), "name": docs["name"], "items": all_items, "stats": stats,
            "transcripts": docs["transcripts"], "missing": docs["missing"]}


def tokens_from_cost_log(since, purpose="guidance"):
    """(calls, input_tokens, output_tokens, cache_hits) for one purpose since a timestamp."""
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


def print_guidance(result):
    print("\n==========", result["ticker"], "|", result["name"], "|", result["stats"]["transcripts"], "transcripts ==========")
    print("call     metric                      target                        period         page speaker")
    for it in result["items"]:
        flag = "" if it["speaker_in_transcript"] else "  [speaker not found in text]"
        print(it["call_quarter"].ljust(8), str(it["metric"])[:27].ljust(27), str(it["target_text"])[:29].ljust(29),
              str(it["period"])[:14].ljust(14), str(it["page"]).rjust(4), str(it["speaker"])[:40] + flag)
    s = result["stats"]
    print("\nquotes: extracted", s["extracted"], "| verified", s["verified"], "| dropped", s["dropped"],
          "| verified rate", s["verified_pct"], "%")
    for t in s["per_transcript"]:
        print("  ", t["quarter"], t["pages"], "pp | extracted", t["extracted"], "verified", t["verified"], "dropped", t["dropped"],
              "|", t["seconds"], "s")
    for m in result["missing"]:
        print("  missing transcript:", m)


if __name__ == "__main__":
    run_started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for symbol in sys.argv[1:] or ["TCS"]:
        result = extract_guidance(symbol)
        if result is None:
            print("\n", symbol, "-> not found on screener")
            continue
        print_guidance(result)
        if "--json" in sys.argv:
            print(json.dumps(result["items"], indent=1, ensure_ascii=False))
    calls, inputs, outputs, cached = tokens_from_cost_log(run_started)
    if calls:
        print("\ntokens this run (purpose=guidance):", calls, "LLM calls,", inputs, "input,", outputs, "output",
              "| per transcript: ~" + str(inputs // calls), "in / ~" + str(outputs // calls), "out | cache hits:", cached)
    else:
        print("\ntokens this run: 0 LLM calls (all", cached, "from cache)")
