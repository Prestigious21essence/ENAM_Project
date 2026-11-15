"""Classify every announcement into a category + priority.

1. Keyword rules on subject + details (written from the real subjects in
   data/subjects_sample.txt). Free and instant.
2. Filings no rule matches, and every litigation-like filing, go to the cheap
   LLM in batches, together with the start of the PDF text. LLM answers are
   cached per filing id, so each filing is sent to the LLM at most once.

Only filings with no category yet are classified; existing ones are never
re-asked (the DB is the source of truth).

Usage:  python push\\classify.py                    (new filings only)
        python push\\classify.py --reclassify-all   (every filing; manual use)
"""
import json
import os
import random
import re
import sys

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from db import get_conn
from llm import call_llm
from pdf_text import get_pdf_text

LLM_CACHE_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "cache", "classify_llm.json")
BATCH_SIZE = 10
PDF_CHARS = 2500        # the first ~600 chars are usually letterhead

HIGH = 3
MEDIUM = 2
LOW = 1

PRIORITY = {
    "results": HIGH, "M&A": HIGH, "management_change": HIGH, "pledging": HIGH,
    "litigation": HIGH, "fund_raise": HIGH,
    "dividend": MEDIUM, "credit_rating": MEDIUM, "capex": MEDIUM, "press_release": MEDIUM,
    "earnings_call": LOW, "investor_meetings": LOW, "insider_trading": LOW,
    "bonus_split": LOW, "postal_ballot": LOW, "agm_egm": LOW, "unclassified": LOW,
}

# ---------- keyword lists (all lowercase) ----------

# Anything that smells like a legal/regulatory matter goes to the LLM, because we
# must check WHO it is about (the company itself, or e.g. a borrower/investee).
LITIGATION_WORDS = ["insolvency", "nclt", "nclat", "tribunal", "court", "penalty",
                    "show cause", "orders passed", "warning letter", "news verification",
                    "rumour verification", "clarification"]

ROUTINE_SUBJECTS = ["copy of newspaper publication", "trading window", "certificate under sebi",
                    "esop/esos/esps", "statement of deviation", "change in auditors",
                    "corrigendum", "amendment to aoa/moa"]
ROUTINE_WORDS = ["newspaper", "esop", "trading window", "certificate under", "certificate pursuant",
                 "share transfer agent", "address of rta", "change in corporate office address",
                 "esg", "auditor", "special window", "physical shares",
                 "redemption of commercial paper", "repayment"]

EARNINGS_CALL_WORDS = ["transcript", "recording", "earnings call", "presentation", "con. call",
                       "investors' call"]
INVESTOR_MEET_WORDS = ["analysts/institutional investor meet", "analyst(s)/investor(s) meet",
                       "analyst presentation", "investors' call"]

# Listing of a subsidiary mentions its "financial results" too, so check this before results
SUBSIDIARY_LISTING_WORDS = ["initial public offer", "trading in equity shares of"]

RESULTS_WORDS = ["submitted to the exchange, the financial results", "financial results for",
                 "financial results of the company", "unaudited financial results",
                 "un-audited financial results", "financial results q", "q2 & h1", "q2 and h1",
                 "performance for q", "results presentation", "earnings presentation",
                 "financial statements for the quarter", "shareholders' letter in lieu of earnings call",
                 "half yearly report", "q2fy27"]   # "Q2FY27" = results press releases (SBI, Apollo)

FUND_RAISE_WORDS = ["qualified institution", "qip", "preferential", "capital raise", "rights issue",
                    "buyback", "buy-back", "conversion of warrants", "issue of securities",
                    "commercial paper", "non convertible", "non-convertible", "debentures", "ncd"]
# Debt issues are routine for lenders like Bajaj Finance -> only medium priority
DEBT_WORDS = ["commercial paper", "non convertible", "non-convertible", "debentures", "ncd"]

MANAGEMENT_WORDS = ["change in management", "change in director", "cessation", "resignation",
                    "retirement", "appointment", "managing director", "chief executive",
                    "chief financial"]

# "joint venture agreement", not just "joint venture": many filings describe a
# partner as "Subsidiary / Joint Venture" without being an M&A event
MNA_WORDS = ["acqui", "merger", "amalgamation", "demerger", "joint venture agreement",
             "wholly owned subsidiary", "takeover", "share purchase agreement",
             "business transfer", "sale of entire stake", "scheme of arrangement"]

AGM_WORDS = ["general meeting", "shareholders meeting", " agm"]
CAPEX_WORDS = ["capex", "capacity expansion", "new plant", "setting up of"]
PRESS_WORDS = ["press release", "bagging/receiving of orders", "media statement", "media release",
               "production volume", "sales in "]


def has_any(text, words):
    for word in words:
        if word in text:
            return True
    return False


def is_litigation_like(subject, details):
    text = (subject + " | " + details).lower()
    return has_any(text, LITIGATION_WORDS)


def classify_by_rules(subject, details):
    """Return a category, or None if no rule is sure."""
    s = subject.lower()
    text = s + " | " + details.lower()

    # Routine paperwork first, so e.g. a newspaper ad of the results stays low
    if has_any(s, ROUTINE_SUBJECTS) or has_any(text, ROUTINE_WORDS):
        return "unclassified"

    if has_any(text, INVESTOR_MEET_WORDS):
        # Look at details only: NSE's subject itself contains "Con. Call"
        if has_any(details.lower(), EARNINGS_CALL_WORDS):
            return "earnings_call"
        return "investor_meetings"

    if has_any(text, SUBSIDIARY_LISTING_WORDS):
        return "M&A"

    # A board-meeting outcome can be results, a fund raise or a dividend.
    # Results win; extra_mentions() notes a dividend / fund raise in the same filing.
    if has_any(text, RESULTS_WORDS) or s == "investor presentation":
        return "results"
    if has_any(text, FUND_RAISE_WORDS) or s in ["qualified institutional placement", "preferential issue"]:
        return "fund_raise"
    if "dividend" in text:
        return "dividend"

    if has_any(text, MANAGEMENT_WORDS):
        return "management_change"
    if has_any(text, MNA_WORDS):
        return "M&A"
    if "credit rating" in text:
        return "credit_rating"
    if "pledge" in text or "encumbrance" in text:
        return "pledging"
    if "regulation 7(2)" in text or "sast" in text:
        return "insider_trading"
    if "postal ballot" in text:
        return "postal_ballot"
    if has_any(text, AGM_WORDS):
        return "agm_egm"
    if has_any(text, CAPEX_WORDS):
        return "capex"
    if has_any(text, PRESS_WORDS):
        return "press_release"
    return None


def extra_mentions(details):
    """For a results filing: does it ALSO announce a dividend or a fund raise?"""
    text = details.lower()
    extras = []
    if "dividend" in text:
        extras.append("dividend")
    if has_any(text, FUND_RAISE_WORDS):
        extras.append("fund raise")
    if len(extras) == 0:
        return None
    return "Board outcome also mentions: " + ", ".join(extras)


def get_priority(category, text, about_listed_company=True, minor=False):
    """text = details (+ LLM summary if any)."""
    priority = PRIORITY.get(category, LOW)
    if category == "fund_raise" and has_any(text.lower(), DEBT_WORDS):
        priority = MEDIUM
    if category == "litigation" and not about_listed_company:
        priority = MEDIUM
    # The LLM flags procedural / tiny / intra-group items (e.g. "hearing adjourned",
    # a Rs 18 lakh fine on Reliance, striking off a dormant subsidiary)
    if category in ["litigation", "M&A", "fund_raise"] and minor:
        priority = MEDIUM
    return priority


def shorten(summary):
    """The cheap model sometimes ignores 'max 20 words': keep the first sentence.
    Only long summaries are cut, and never in the first 60 characters, so titles
    like "Dr. " or "Mr. " don't end the sentence early."""
    if not summary or len(summary) <= 200:
        return summary
    # a sentence ends at ". " or ".Next" ("…2026.Further, a meeting…"), but not at an abbreviation
    protected = re.sub(r"\b(Rs|Mr|Mrs|Ms|Dr|No|Ltd|Pvt|Inc|w\.e\.f|i\.e|e\.g|viz|Co)\.", lambda a: a.group(0).replace(".", "·"), summary)
    m = re.compile(r"\.(?=\s|[A-Z])").search(protected, 60)
    if m:
        summary = summary[:m.start() + 1]
    if len(summary) > 200:
        # never cut a word in half: back up to the last space
        space = summary.rfind(" ", 100, 197)
        summary = summary[:space if space != -1 else 197].rstrip(",;:-") + "…"
    return summary


# ---------- LLM part ----------

LLM_PROMPT = """You classify Indian stock-exchange filings for an investor.
Use ONLY the text given. Categories:
results (the listed company's OWN quarterly results, results press release/deck/shareholder
  letter; a parent or group company's results are press_release),
M&A (acquisition, merger, demerger, JV, buying/selling a stake in a subsidiary),
fund_raise (QIP, rights, preferential allotment, buyback, debentures, commercial paper),
management_change (CEO/CFO/MD/director joining, resigning, retiring),
litigation (lawsuits, regulatory orders, fines, insolvency proceedings),
insider_trading (promoter/insider buying or selling own shares),
earnings_call (call notice, transcript, recording),
investor_meetings (meetings with investors/funds, investor conferences),
credit_rating, dividend, bonus_split,
capex (new plant / capacity expansion spend),
press_release (order wins, products, partnerships, rumour clarifications, monthly sales),
postal_ballot, agm_egm, pledging,
unclassified (routine paperwork that does not move the stock).

For litigation, decide "about_listed_company": true if the listed company itself is
the one sued, penalised, ordered, or facing insolvency; false if the case is about
another party (e.g. a borrower, customer, investee company, or the company is the
creditor). For other categories set it to true.

Set "minor": true if the filing is procedural (hearing adjourned or rescheduled),
the amount is tiny for a company of this size (e.g. a fine of a few lakh rupees),
or it is purely internal to the group (one subsidiary investing in another,
striking off a dormant subsidiary). Otherwise false.

Return a JSON list, one object per filing, in this exact form:
[{"id": "...", "category": "...", "about_listed_company": true, "minor": false,
  "summary": "ONE short factual sentence, max 20 words, with the key number if any"}]

Filings:
"""


def load_llm_cache():
    if os.path.exists(LLM_CACHE_PATH):
        with open(LLM_CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_llm_cache(cache):
    os.makedirs(os.path.dirname(LLM_CACHE_PATH), exist_ok=True)
    with open(LLM_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=1)


def classify_with_llm(items):
    """items: list of dicts with id, symbol, subject, details, pdf_url.
    Returns {id: {"category", "about_listed_company", "summary"}}."""
    cache = load_llm_cache()
    todo = []
    for it in items:
        if it["id"] not in cache:
            todo.append(it)
    print("LLM items:", len(items), "| already cached:", len(items) - len(todo), "| to send:", len(todo))

    for start in range(0, len(todo), BATCH_SIZE):
        batch = todo[start:start + BATCH_SIZE]
        prompt = LLM_PROMPT
        for it in batch:
            pdf_text = " ".join(get_pdf_text(it["pdf_url"], max_pages=2).split())[:PDF_CHARS]
            prompt = prompt + "\n---\nid: " + it["id"] + "\ncompany: " + it["symbol"] \
                + "\nsubject: " + it["subject"] + "\ndetails: " + it["details"] \
                + "\npdf text: " + pdf_text + "\n"

        print("  sending batch of", len(batch), "...")
        try:
            answer = call_llm(prompt, json_output=True, purpose="classify", temperature=0)
        except RuntimeError as e:
            # Don't crash the whole run: these filings stay low and are retried next run
            print("  LLM unavailable, skipping this batch:", str(e)[:80])
            continue
        try:
            results = json.loads(answer)
        except json.JSONDecodeError:
            print("  could not parse LLM answer, skipping batch:", answer[:200])
            continue

        for r in results:
            category = r.get("category")
            if category not in PRIORITY:
                category = "unclassified"
            about = r.get("about_listed_company")
            if about is None:
                about = True
            minor = r.get("minor") is True
            cache[r.get("id")] = {"category": category, "about_listed_company": about,
                                  "minor": minor, "summary": shorten(r.get("summary"))}
        save_llm_cache(cache)

    answers = {}
    for it in items:
        if it["id"] in cache:
            answers[it["id"]] = cache[it["id"]]
    return answers


# ---------- main ----------

def classify_all(reclassify_all=False):
    """Classify the filings that have no category yet (the new ones).

    The database is the source of truth: an existing classification is never
    re-asked, because the daily job on GitHub has no LLM cache and the model's
    answers drift between runs. reclassify_all=True re-runs every filing
    (manual use only); even then a hand-set one (classified_by = 'manual') is kept."""
    conn = get_conn()
    if reclassify_all:
        rows = conn.execute(
            "SELECT id, symbol, subject, details, pdf_url, summary FROM announcements "
            "WHERE classified_by IS NULL OR classified_by != 'manual'").fetchall()
    else:
        rows = conn.execute(
            "SELECT id, symbol, subject, details, pdf_url, summary FROM announcements "
            "WHERE category IS NULL").fetchall()
    print("  filings to classify:", len(rows), "(all)" if reclassify_all else "(new only)")

    results = {}          # id -> (category, priority, classified_by, summary)
    llm_items = []
    for row_id, symbol, subject, details, pdf_url, summary in rows:
        subject = subject or ""
        details = details or ""
        category = None
        if not is_litigation_like(subject, details):
            category = classify_by_rules(subject, details)
        if category is not None:
            if category == "results" and summary is None:
                summary = extra_mentions(details)
            results[row_id] = (category, get_priority(category, details), "rule", summary)
        else:
            llm_items.append({"id": row_id, "symbol": symbol, "subject": subject,
                              "details": details, "pdf_url": pdf_url, "summary": summary})

    answers = classify_with_llm(llm_items)
    for it in llm_items:
        answer = answers.get(it["id"])
        if answer is None:
            # LLM failed for this one: keep it visible but low, try again next run
            results[it["id"]] = ("unclassified", LOW, None, it["summary"])
            continue
        text = it["details"] + " " + (answer["summary"] or "")
        priority = get_priority(answer["category"], text, answer["about_listed_company"],
                                answer.get("minor", False))
        # Prefer the LLM's one-liner; NSE's own summary can be a whole paragraph
        summary = answer["summary"] or it["summary"]
        results[it["id"]] = (answer["category"], priority, "llm", summary)

    for row_id in results:
        category, priority, classified_by, summary = results[row_id]
        conn.execute(
            "UPDATE announcements SET category = ?, priority = ?, classified_by = ?, summary = ? WHERE id = ?",
            (category, priority, classified_by, summary, row_id))
    conn.commit()
    conn.close()
    return results


if __name__ == "__main__":
    results = classify_all(reclassify_all="--reclassify-all" in sys.argv)
    if not results:
        print("Nothing new to classify (use --reclassify-all to re-run every filing).")
        sys.exit(0)

    high = 0
    medium = 0
    low = 0
    by_llm = 0
    for category, priority, classified_by, summary in results.values():
        if priority == HIGH:
            high = high + 1
        elif priority == MEDIUM:
            medium = medium + 1
        else:
            low = low + 1
        if classified_by == "llm":
            by_llm = by_llm + 1

    print("\n" + str(len(results)), "filings ->", high, "high,", medium, "medium,", low, "low;",
          by_llm, "needed the LLM")

    conn = get_conn()
    rows = conn.execute(
        "SELECT symbol, priority, category, classified_by, subject, details, summary FROM announcements").fetchall()
    conn.close()
    print("\n10 random rows:")
    for symbol, priority, category, classified_by, subject, details, summary in random.sample(rows, 10):
        print("-", symbol, "| P" + str(priority), category, "(" + str(classified_by) + ") |",
              subject, "|", (details or "")[:110])
        if classified_by == "llm":
            print("     summary:", summary)
