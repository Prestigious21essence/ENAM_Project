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
import re
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
# A CEO of one division/region/business/complex is senior management, not the company's top job
DIVISION_WORDS = ["division", "region", "ic head", "business", " - ", " – ", "complex", "unit", "plant", "segment", "vertical", "subsidiary"]

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


# ---------- Python rules on top of the model's reading (found by the 15 Nov audit) ----------

CORRECTION_WORDS = ["may please be read as", "may be read as", "corrigendum", "should be read as", "typographical error"]
OTHER_ORG_WORDS = ["drdo", "ministry", "government of india", "secretary", " ias", " irs", "department of"]
JOIN_VERBS = re.compile(r"\b(appoint(ed|ment|s)?|assum(e|ed|es) (charge|office|the position)|join(ed|s|ing)?|designat(ed|ion)|"
                        r"elevat(ed|ion)|promot(ed|ion)|nominat(ed|ion)|induct(ed|ion)|take[sn]? over)\b", re.I)
LEAVE_VERBS = re.compile(r"\b(resign(ed|ation|s)?|ceas(e|ed|es)|cessation|retir(e|ed|ement|es)|superannuat(ed|ion)|vacat(e|ed|ion)|"
                         r"relinquish(ed)?|withdraw(al|n)?|step(s|ped)? down|completion of (his|her|the) (tenure|term)|demise|passed away)\b", re.I)
CHANGE_VERBS = re.compile(r"\b(continue[sd]? (to be|as)|re-?designat(ed|ion)|promot(ed|ion)|elevat(ed|ion)|additional charge|transition)\b", re.I)
REAPPOINT_VERBS = re.compile(r"\bre-?appoint(ed|ment)\b", re.I)


def surname_of(name):
    """The longest word of the name (not an initial: 'Venkateswaran L' -> 'venkateswaran')."""
    words = [w for w in re.findall(r"[A-Za-z']+", name or "") if len(w) >= 3]
    if not words:
        return ""
    return max(words, key=len).lower()


def context_around(text, name, width=350):
    """The filing text around every mention of the person's surname (joined)."""
    surname = surname_of(name)
    if not surname:
        return ""
    low = text.lower()
    parts = []
    start = 0
    while True:
        i = low.find(surname, start)
        if i < 0 or len(parts) >= 4:
            break
        parts.append(text[max(0, i - width):i + width])
        start = i + len(surname)
    return " ... ".join(parts)


def sentences_with(text, name):
    """Only the sentences that mention the person (so a phrase about someone else can't apply)."""
    surname = surname_of(name)
    if not surname:
        return ""
    out = []
    # abbreviations must not end a sentence ("w.e.f. close of business", "Mr. Nayak");
    # a sentence can end with a period followed by a closing quote: 'Annexure - 66A". He shall...'
    protected = re.sub(r"\b(w\.e\.f|Mr|Mrs|Ms|Dr|Shri|Smt|Prof|No|Ltd|Pvt|Inc|i\.e|e\.g|viz|Sl|Sr|Regn|Co)\.",
                       lambda m: m.group(0).replace(".", "·"), text, flags=re.I)
    sentences = re.split(r"(?<=[.;])[\"”’']?\s+", protected)
    for i, sentence in enumerate(sentences):
        if surname in sentence.lower():
            out.append(sentence)
            # "He shall continue to be a Non-executive Director": the next sentences, when they
            # start with a pronoun, are still about the same person
            for j in (i + 1, i + 2):
                if j < len(sentences) and re.match(r"(He|She|His|Her)\b", sentences[j]):
                    out.append(sentences[j])
    return " ".join(out)


def verb_check(change, ctx):
    """Does the filing text near the name contain a verb that matches the change? Returns
    (ok, verbs found as a short string)."""
    found = []
    if JOIN_VERBS.search(ctx):
        found.append("join")
    if LEAVE_VERBS.search(ctx):
        found.append("leave")
    if CHANGE_VERBS.search(ctx):
        found.append("change")
    if REAPPOINT_VERBS.search(ctx):
        found.append("reappoint")
    kind = change.get("change")
    needed = {"joining": "join", "leaving": "leave", "role_change": "change", "reappointed": "reappoint"}.get(kind)
    if kind == "role_change" and ("join" in found or "leave" in found) and "change" not in found:
        found.append("change")        # a re-designation is often worded as appoint + cease
    return (needed in found) if needed else False, "+".join(found) or "none"


def apply_rules(changes, text):
    """Fix the model's reading with plain rules and record what was changed.
    Returns (changes, notes). A correction filing yields no change at all."""
    flat = " ".join(text.split())
    low = flat.lower()
    notes = []
    if any(w in low for w in CORRECTION_WORDS):
        return [], ["correction of an earlier filing (\"may please be read as\"): no management change"]
    kept = []
    for change in changes:
        name = change.get("name") or ""
        # no person, no role or no kind of change: the model found nothing real (e.g. a filing that
        # merely authorises officers to decide materiality)
        if not name.strip() or not (change.get("role") or "").strip() or change.get("change") not in ("joining", "leaving", "role_change", "reappointed"):
            notes.append("dropped an entry with no name, role or change kind")
            continue
        ctx = context_around(flat, name)
        own = sentences_with(flat, name)          # rules about the person use only their own sentences
        own_low = own.lower()
        role = change.get("role", "") or ""

        # a role at another organisation (a government nominee's DRDO / ministry title) is not a role here
        if any(w in (" " + role.lower()) for w in OTHER_ORG_WORDS):
            if "nominee" in low or "official director" in low:
                change["role"] = "Government Nominee Director"
                notes.append(name + ": role '" + role + "' is at another organisation; shown as Government Nominee Director")
                role = change["role"]
            else:
                notes.append(name + ": dropped, role '" + role + "' is at another organisation")
                continue

        # giving up an ADDITIONAL charge is not leaving the company
        if "additional charge" in own_low and change.get("change") == "leaving":
            m = re.search(r",\s*([A-Z][^,.;]{3,60}?) of the company,?\s+ceased to hold the additional charge", own, re.I)
            main_role = m.group(1).strip() if m else None
            change["change"] = "role_change"
            change["detail"] = "gives up the additional charge of " + role + ((", remains " + main_role) if main_role else "")
            change["role"] = role + " (additional charge given up)"
            change["reason"] = ""
            notes.append(name + ": 'leaving' -> gives up an additional charge" + ((", remains " + main_role) if main_role else ""))

        # "shall continue to be a Non-executive Director": a role change, not an exit
        # (continuing only as an employee, after giving up the role, is still a departure from the role)
        elif re.search(r"(shall|will) continue (to be|as)|continues (to be|as)", own_low) and change.get("change") == "leaving":
            m = re.search(r"continue[s]? (?:to be|as) (?:an? )?([A-Z][A-Za-z\- ]{3,50}?)(?: of the company|[.,;])", own, re.I)
            new_role = m.group(1).strip() if m else ""
            if any(w in new_role.lower() for w in ("director", "chairman", "board", "member", "chief", "officer", "president")):
                change["change"] = "role_change"
                change["detail"] = "steps down as " + role + ", continues as " + new_role
                change["role"] = new_role
                change["reason"] = ""
                notes.append(name + ": 'leaving' -> steps down as " + role + ", continues as " + new_role)

        ok, verbs = verb_check(change, ctx)
        if not ok and ctx:
            # the text says the opposite of the card: trust the text's verbs when they are unambiguous
            if change.get("change") == "leaving" and "join" in verbs and "leave" not in verbs:
                change["change"] = "joining"
                notes.append(name + ": 'leaving' -> 'joining' (text has only appointment verbs)")
            elif change.get("change") == "joining" and "leave" in verbs and "join" not in verbs:
                change["change"] = "leaving"
                notes.append(name + ": 'joining' -> 'leaving' (text has only cessation verbs)")
            else:
                notes.append(name + ": verbs near the name (" + verbs + ") don't confirm '" + str(change.get("change")) + "' - check")
        change["verbs_in_filing"] = verbs
        kept.append(change)
    return kept, notes


def headline(change):
    name = change.get("name", "?")
    role = change.get("role", "")
    date = change.get("effective_date", "")
    kind = change.get("change", "")

    if change.get("detail"):
        text = name[0].upper() + name[1:] + ": " + change["detail"]
        if date:
            text = text + ", effective " + date
        return text
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
    changes, rule_notes = apply_rules(changes, get_pdf_text(pdf_url))
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
            "pdf_url": pdf_url, "changes": changes, "rule_notes": rule_notes}


def recheck_cards():
    """Apply the rules to every saved card (no LLM) and re-save the ones that change.
    Returns a list of (announcement_id, symbol, notes) for the corrected cards."""
    conn = get_conn()
    rows = conn.execute("SELECT announcement_id, symbol, card FROM mgmt_cards ORDER BY symbol").fetchall()
    conn.close()
    corrected = []
    for announcement_id, symbol, card_json in rows:
        card = json.loads(card_json)
        before = json.dumps(card.get("changes"), sort_keys=True)
        text = get_pdf_text(card["pdf_url"])
        changes, notes = apply_rules(card.get("changes", []), text)
        for change in changes:
            change["headline"] = headline(change)
            change["seniority"] = seniority(change.get("role"))
        card["changes"] = changes
        card["rule_notes"] = notes
        if json.dumps(changes, sort_keys=True) != before:
            save_card(card)
            corrected.append((announcement_id, symbol, notes))
        elif notes:
            corrected.append((announcement_id, symbol, ["(unchanged) "] + notes))
    return corrected


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
