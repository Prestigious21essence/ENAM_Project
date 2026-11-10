"""One-line summaries for filings whose NSE text says nothing
(e.g. "X has informed the Exchange about Acquisition").

Only for the categories that can reach the top of the digest; results and
management changes get their own cards instead. Batched (10 filings per LLM
call) and cached through llm.py, so each filing costs tokens only once.
"""
import json
import os
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


def is_vague(details):
    """NSE's generic one-liners: 'X has informed the Exchange about <subject>'."""
    if not details:
        return True
    return "informed the exchange about" in details.lower() and len(details) < 130


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
    for start in range(0, len(todo), BATCH_SIZE):
        batch = todo[start:start + BATCH_SIZE]
        prompt = PROMPT
        for row_id, symbol, subject, details, pdf_url in batch:
            pdf_text = " ".join(get_pdf_text(pdf_url, max_pages=2).split())[:PDF_CHARS]
            prompt = prompt + "\n---\nid: " + row_id + "\ncompany: " + symbol + "\nsubject: " \
                + subject + "\npdf text: " + pdf_text + "\n"
        try:
            answer = call_llm(prompt, json_output=True, purpose="summarize", temperature=0)
            results = json.loads(answer)
        except Exception as e:
            print("  summary batch failed, will retry next refresh:", str(e)[:80])
            continue
        for r in results:
            if r.get("id") and r.get("summary"):
                conn.execute("UPDATE announcements SET summary = ? WHERE id = ?", (r["summary"], r["id"]))
                done = done + 1
        conn.commit()
    conn.close()
    return done


if __name__ == "__main__":
    print("Summarised:", summarize_vague_filings())
