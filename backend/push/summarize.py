"""One-line summaries for filings whose NSE text says nothing
(e.g. "X has informed the Exchange about Acquisition").

Only for the categories that can reach the top of the digest; results and
management changes get their own cards instead. Batched (10 filings per LLM
call) and cached through llm.py, so each filing costs tokens only once.
"""
import json
import os
import re
import sys

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from db import get_conn
from llm import call_llm
from pdf_text import get_pdf_text

CATEGORIES = ["M&A", "fund_raise", "litigation", "credit_rating", "dividend", "capex",
              "press_release", "pledging", "insider_trading"]
BATCH_SIZE = 10
PDF_CHARS = 2500

PROMPT = """For each Indian stock-exchange filing below, write ONE factual sentence (max 20 words)
saying what actually happened, with the key number if there is one. Use ONLY the given text.
Return JSON: [{"id": "...", "summary": "..."}]

Filings:
"""


MONEY = re.compile(r"(₹|rs\.?|inr)\s?([\d,]+(?:\.\d+)?)\s?(million|mn|billion|bn)\b", re.I)


def money_in_crore(text):
    """'₹130,000 million' -> '₹13,000 cr', 'INR 2.5 billion' -> '₹250 cr': one unit everywhere."""
    def convert(m):
        value = float(m.group(2).replace(",", ""))
        unit = m.group(3).lower()
        crore = value / 10 if unit in ("million", "mn") else value * 100
        return "₹" + ("{:,.1f}".format(crore) if crore < 100 else "{:,.0f}".format(crore)) + " cr"
    return MONEY.sub(convert, text or "")


def is_vague(details):
    """NSE's generic one-liners: 'X has informed the Exchange about/regarding <subject>',
    'Please find attached…', or nothing at all."""
    if not details:
        return True
    low = details.lower().strip()
    if "informed the exchange" in low:
        return True
    if "please find attached" in low or "please find enclosed" in low or len(details) < 60:
        return True
    # the filing's own covering-letter prose, not a headline
    if low.startswith(("we wish to inform", "this is to inform", "pursuant to", "in continuation", "further to", "with reference to")):
        return True
    return False


NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def verified_summary(summary, source_text):
    """Every number and every capitalised name in the model's sentence must appear in the
    filing text (numbers compared without commas); otherwise the sentence is not used."""
    if not summary:
        return False
    source = " ".join(source_text.split()).lower()
    source_numbers = set(n.replace(",", "") for n in NUMBER.findall(source))
    for n in NUMBER.findall(summary):
        if n.replace(",", "") not in source_numbers and n.replace(",", "") not in source:
            return False
    for name in re.findall(r"\b[A-Z][a-zA-Z&'\-]{2,}\b", summary):
        if name.lower() in ("the", "this", "its", "for", "and", "with", "from", "has", "was", "were", "will", "after", "under", "between"):
            continue
        if name.lower() not in source:
            return False
    return True


def cleaned_subject(subject, details):
    """A readable fallback from the filing's own subject line (never a cut-off word)."""
    text = subject or ""
    titled = re.search(r"titled\s*[\"“']\s*(.+?)\s*[\"”']", details or "", re.I)
    about = re.search(r"(?:about|regarding)\s+(.+)$", details or "", re.I)
    if titled:
        text = titled.group(1)                      # the press release's own title
    elif about and len(about.group(1)) > len(text):
        text = about.group(1)
    text = " ".join(text.split()).strip("'\"“”").rstrip(".")
    if text:
        text = text[0].upper() + text[1:]
    if len(text) > 160:
        text = text[:text.rfind(" ", 80, 160)] + "…"
    return text


def summarize_vague_filings():
    conn = get_conn()
    placeholders = ",".join("?" for c in CATEGORIES)
    rows = conn.execute(
        "SELECT id, symbol, subject, details, pdf_url FROM announcements "
        "WHERE summary IS NULL AND category IN (" + placeholders + ")", CATEGORIES).fetchall()

    todo = []
    for row in rows:
        if is_vague(row[3]):
            todo.append(row)
    print("Vague filings to summarise:", len(todo))

    done = 0
    fallback = 0
    for start in range(0, len(todo), BATCH_SIZE):
        batch = todo[start:start + BATCH_SIZE]
        prompt = PROMPT
        sources = {}
        for row_id, symbol, subject, details, pdf_url in batch:
            pdf_text = " ".join(get_pdf_text(pdf_url, max_pages=2).split())[:PDF_CHARS]
            sources[row_id] = (subject or "") + " " + (details or "") + " " + pdf_text
            prompt = prompt + "\n---\nid: " + row_id + "\ncompany: " + symbol + "\nsubject: " \
                + subject + "\npdf text: " + pdf_text + "\n"
        try:
            answer = call_llm(prompt, json_output=True, purpose="summarize", temperature=0)
            results = json.loads(answer)
        except Exception as e:
            print("  summary batch failed, will retry next refresh:", str(e)[:80])
            continue
        answers = {}
        for r in results:
            if r.get("id") and r.get("summary"):
                answers[r["id"]] = r["summary"]
        for row_id, symbol, subject, details, pdf_url in batch:
            summary = money_in_crore(answers.get(row_id, ""))
            # Python check: every number and name in the sentence must be in the filing
            if not verified_summary(summary, money_in_crore(sources[row_id]) + " " + sources[row_id]):
                summary = cleaned_subject(subject, details)
                fallback = fallback + 1
            conn.execute("UPDATE announcements SET summary = ? WHERE id = ?", (summary, row_id))
            done = done + 1
        conn.commit()
    conn.close()
    if fallback:
        print("  summaries that failed the number/name check and fell back to the subject:", fallback)
    return done


if __name__ == "__main__":
    print("Summarised:", summarize_vague_filings())
