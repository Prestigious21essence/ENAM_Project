"""Management-change card: who is joining/leaving, in what role, from when, and a short bio.

How it works:
  1. Take the filing's PDF text. Long filings (e.g. a board outcome that is mostly
     results) are cut down to the chunks that talk about appointments/resignations.
     If the PDF has no text layer, the first pages are sent as images instead.
  2. The cheap LLM lists every person who joins/leaves, with role, date, reason and a
     1-2 sentence bio taken ONLY from the filing (appointment filings must include a
     "brief profile" under SEBI rules).
  3. If a joiner has no bio here (filings often say "details already provided in our
     earlier intimation"), look for the person in the company's earlier management
     filings and take the bio from there.
  4. Python writes the one-line headlines.

Usage:  python push\\mgmt_change.py NSE-106829496 NSE-106845110
"""
import json
import os
import sys

import pymupdf

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from db import get_conn
from llm import call_llm
from pdf_text import get_pdf_path, get_pdf_text

MAX_CHARS = 8000
CHUNK_CHARS = 1500
CHUNKS_TO_KEEP = 5
MGMT_WORDS = ["appoint", "resign", "cessation", "cease", "retire", "succession", "profile",
              "brief", "chief", "director", "managing", "officer", "experience", "tenure",
              "vacat", "designat", "assumed charge", "qualification", "senior management"]

# Seniority is decided in Python from the role, so it is the same on every run
# Not "executive director": in PSUs (e.g. HAL) that is a below-board title, and it
# also matches "Non-Executive Director". Board-level executives are "whole-time directors".
TOP_ROLE_WORDS = ["managing director", "md ", "md&", "ceo", "chief executive", "cfo",
                  "chief financial", "chairman", "chairperson", "whole-time", "whole time"]
# A CEO of one division/region/business is senior management, not the company's top job
DIVISION_WORDS = ["division", "region", "ic head", "business", " - ", " – "]

PROMPT = """This is a stock-exchange filing by {company} about a change in its management or board.
Use ONLY this text. List every person who joins, leaves, or changes role.

Return JSON:
{{"changes": [
  {{"name": "full name without Mr/Ms/Dr",
   "role": "role exactly as stated",
   "change": "joining" or "leaving" or "role_change" or "reappointed",
   "effective_date": "the date the change takes effect, as stated (look for 'effective', 'w.e.f.', 'close of business'); else empty",
   "reason": "for leaving: the stated reason, max 12 words (e.g. completion of tenure, personal reasons, superannuation). Praise or thanks for their work is NOT a reason. Else empty",
   "bio": "for joining / role change: 1-2 sentences from the text (experience, previous employers, education); empty if the text has none"}}
]}}
If the filing contains no management change, return {{"changes": []}}.

Filing text:
{text}
"""


def relevant_text(text):
    """Keep short texts whole; from long ones keep the 4 chunks with most management words."""
    text = " ".join(text.split())
    if len(text) <= MAX_CHARS:
        return text

    chunks = []
    for start in range(0, len(text), CHUNK_CHARS):
        chunk = text[start:start + CHUNK_CHARS]
        lower = chunk.lower()
        score = 0
        for word in MGMT_WORDS:
            score = score + lower.count(word)
        chunks.append((score, start, chunk))

    best = sorted(chunks, reverse=True)[:CHUNKS_TO_KEEP]
    best = sorted(best, key=lambda c: c[1])        # back to reading order
    parts = []
    for score, start, chunk in best:
        parts.append(chunk)
    return " ... ".join(parts)


def page_images(pdf_url, max_pages=3):
    try:
        doc = pymupdf.open(get_pdf_path(pdf_url))
    except Exception:
        return []
    images = []
    for i in range(min(max_pages, len(doc))):
        images.append(doc[i].get_pixmap(dpi=120).tobytes("png"))
    doc.close()
    return images


def extract_changes(symbol, pdf_url):
    text = get_pdf_text(pdf_url)
    images = None
    if len(text.strip()) < 200:
        # No text layer (scanned): let the model read the pages
        images = page_images(pdf_url)
        if len(images) == 0:
            return []
        text = "(see the attached page images)"
    prompt = PROMPT.format(company=symbol, text=relevant_text(text))
    answer = call_llm(prompt, json_output=True, purpose="mgmt_card", images=images)
    data = json.loads(answer)
    if isinstance(data, list):
        data = {"changes": data}
    return data.get("changes", [])


def same_person(name_a, name_b):
    """Match on surname, ignoring case (filings write 'Mr. Anup Bagchi' or 'Anup Bagchi')."""
    surname_a = name_a.lower().split()[-1]
    surname_b = name_b.lower().split()[-1]
    return surname_a == surname_b


def find_earlier_bio(symbol, name, before_datetime):
    """Look through the company's earlier management filings for this person's bio."""
    surname = name.split()[-1].lower()
    conn = get_conn()
    rows = conn.execute(
        "SELECT pdf_url FROM announcements WHERE symbol = ? AND category = 'management_change' "
        "AND datetime < ? ORDER BY datetime DESC LIMIT 6", (symbol, before_datetime)).fetchall()
    conn.close()

    for row in rows:
        pdf_url = row[0]
        if surname not in get_pdf_text(pdf_url).lower():
            continue
        for person in extract_changes(symbol, pdf_url):
            if same_person(person.get("name", ""), name) and person.get("bio"):
                return person["bio"], pdf_url
    return None, None


def seniority(role):
    """top = CEO/MD/CFO/Chairman/whole-time director, board = other directors, other = the rest."""
    text = (role or "").lower() + " "
    if "chairman" in text or "chairperson" in text:     # often non-executive, still the top job
        return "top"
    if "non-executive" in text or "non executive" in text or "independent" in text:
        return "board"
    for word in TOP_ROLE_WORDS:
        if word in text:
            for division_word in DIVISION_WORDS:
                if division_word in text:
                    return "other"
            return "top"
    if "director" in text:
        return "board"
    return "other"


def headline(change):
    name = change.get("name", "?")
    role = change.get("role", "")
    date = change.get("effective_date", "")
    kind = change.get("change", "")

    if kind == "leaving":
        text = "Leaving: " + name + ", " + role
        if change.get("reason"):
            text = text + " (" + change["reason"] + ")"
    elif kind == "reappointed":
        text = "Re-appointed: " + name + " as " + role
    elif kind == "role_change":
        text = "New role: " + name + " as " + role
    else:
        text = "Joining: " + name + " as " + role
    if date:
        text = text + ", effective " + date
    return text


def build_card(announcement_id):
    conn = get_conn()
    row = conn.execute("SELECT symbol, datetime, pdf_url FROM announcements WHERE id = ?",
                       (announcement_id,)).fetchone()
    conn.close()
    symbol, filed_at, pdf_url = row

    changes = extract_changes(symbol, pdf_url)
    for change in changes:
        change["headline"] = headline(change)
        change["seniority"] = seniority(change.get("role"))
        change["bio_source"] = "this filing"
        if change.get("change") in ["joining", "role_change"] and not change.get("bio"):
            bio, source_url = find_earlier_bio(symbol, change.get("name", ""), filed_at)
            if bio:
                change["bio"] = bio
                change["bio_source"] = source_url
            else:
                change["bio_source"] = None

    return {"symbol": symbol, "announcement_id": announcement_id, "filed_at": filed_at,
            "pdf_url": pdf_url, "changes": changes}


def save_card(card):
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO mgmt_cards VALUES (?, ?, ?)",
                 (card["announcement_id"], card["symbol"], json.dumps(card)))
    conn.commit()
    conn.close()


def print_card(card):
    print("\n==========", card["symbol"], "management change (filed", card["filed_at"] + ") ==========")
    if len(card["changes"]) == 0:
        print("(no management change found in this filing)")
    for change in card["changes"]:
        print("-", change["headline"], "[" + str(change.get("seniority")) + "]")
        if change.get("bio"):
            print("    Bio:", change["bio"])
            if change["bio_source"] != "this filing":
                print("    (bio from earlier filing:", change["bio_source"] + ")")
    print("Source:", card["pdf_url"])


if __name__ == "__main__":
    for announcement_id in sys.argv[1:]:
        card = build_card(announcement_id)
        save_card(card)
        print_card(card)
