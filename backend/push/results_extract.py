"""Results card: headline numbers from a quarterly results PDF, with QoQ and YoY.

How it works:
  1. Find the P&L page in the PDF with simple keyword scoring (no LLM).
  2. Render that page as an image and ask the cheap LLM to read the raw line
     items for 3 columns: this quarter, last quarter, same quarter last year.
     (An image, not text: some filings, e.g. SBI's, are scanned and their text
     layer is garbled OCR. Gemini reads the table image reliably.)
  3. Python does all the maths: unit conversion to Rs crore, EBITDA, QoQ, YoY.

Companies:  Revenue, EBITDA, PBT, PAT  (consolidated statement)
Banks:      Net interest income, Operating profit (pre-provision), PBT, PAT
            (standalone statement; banks have no "revenue" or EBITDA line)

Usage:  python push\\results_extract.py TCS ITC SBIN
"""
import json
import os
import sys

import pymupdf

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from db import get_conn
from llm import call_llm
from pdf_text import get_pdf_path

MAX_SCANNED_PAGES = 4

PL_WORDS = ["revenue from operations", "other income", "finance cost", "depreciation",
            "profit before tax", "tax expense", "employee", "total income", "total expenses",
            "net profit", "interest", "provisions", "operating profit"]

COMPANY_PROMPT = """This image is the profit and loss table from an Indian company's quarterly
results filing. Read the {statement} figures for exactly three columns:
  1. the latest quarter, 2. the previous quarter, 3. the same quarter one year earlier.
Copy numbers exactly as printed (no maths). Use a negative number if shown in brackets.
If a line does not exist, use 0.

Return JSON:
{{"unit": "unit as printed, e.g. Rs crore / Rs lakh / Rs million",
 "statement": "consolidated or standalone (what you actually read)",
 "periods": [
  {{"label": "quarter end date as printed",
   "revenue": "Revenue from operations",
   "excise_duty": "Excise duty (an expense line; 0 if none)",
   "other_income": "Other income",
   "share_of_associates": "Share of profit/(loss) of associates and joint ventures (0 if none)",
   "finance_costs": "Finance costs",
   "depreciation": "Depreciation and amortisation",
   "exceptional_items": "Exceptional items, positive if it ADDS to profit, negative if a loss",
   "pbt": "Profit before tax",
   "pat": "Profit for the period (after tax)"}}
 ]}}
"""

BANK_PROMPT = """This image is the profit and loss table from an Indian bank's quarterly
results filing. Read the STANDALONE figures for exactly three columns:
  1. the latest quarter, 2. the previous quarter, 3. the same quarter one year earlier.
Copy numbers exactly as printed (no maths). If a line does not exist, use 0.

Return JSON:
{"unit": "unit as printed, e.g. Rs crore / Rs lakh",
 "statement": "standalone or consolidated (what you actually read)",
 "periods": [
  {"label": "quarter end date as printed",
   "interest_earned": "Interest earned (total)",
   "interest_expended": "Interest expended",
   "operating_profit": "Operating profit before provisions and contingencies",
   "exceptional_items": "Exceptional items, positive if it ADDS to profit, 0 if none",
   "pbt": "Profit from ordinary activities before tax",
   "pat": "Net profit for the period"}
 ]}
"""


# ---------- step 1: find the P&L page ----------

def is_bank(doc):
    """Banks' results cite the Banking Regulation Act; companies (and NBFCs) don't."""
    for page in doc:
        if "banking regulation act" in page.get_text().lower():
            return True
    return False


def find_pl_page(doc, bank):
    """Return the index of the page that looks most like the P&L table.
    For companies prefer a consolidated page, for banks a standalone one."""
    best_page = None
    best_score = 0
    for i in range(len(doc)):
        text = doc[i].get_text().lower()
        score = 0
        for word in PL_WORDS:
            if word in text:
                score = score + 1
        if bank and "standalone" in text:
            score = score + 2
        if not bank and "consolidated" in text:
            score = score + 2
        if score > best_score:
            best_score = score
            best_page = i
    if best_score < 4:          # a cover letter mentioning "results" is not a P&L table
        return None
    return best_page


# ---------- step 3: maths in Python ----------

def to_number(value):
    """LLM may return '1,234.5', '(12.3)' or a number."""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace(",", "").replace("₹", "").strip()
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()")
    try:
        number = float(text)
    except ValueError:
        return 0.0
    if negative:
        number = -number
    return number


def crore_factor(unit):
    unit = unit.lower()
    if "lakh" in unit or "lac" in unit:
        return 0.01
    if "million" in unit:
        return 0.1
    if "billion" in unit:
        return 100.0
    return 1.0          # crore


def pct_change(new, old):
    if old == 0:
        return None
    return round((new - old) / abs(old) * 100, 1)


def build_metrics(raw, bank):
    """raw = LLM JSON. Returns list of 3 dicts with the 4 headline numbers in Rs crore."""
    factor = crore_factor(raw.get("unit", "crore"))
    periods = []
    for p in raw["periods"][:3]:
        values = {}
        for key in p:
            if key != "label":
                values[key] = to_number(p[key]) * factor

        if bank:
            metrics = {
                "Net interest income": values.get("interest_earned", 0) - values.get("interest_expended", 0),
                "Operating profit": values.get("operating_profit", 0),
                "PBT": values.get("pbt", 0),
                "PAT": values.get("pat", 0),
            }
        else:
            # EBITDA is rarely printed, so we build it from PBT:
            #   PBT - exceptional items - share of associates (not operating)
            #   + finance costs + depreciation - other income
            ebitda = (values.get("pbt", 0) - values.get("exceptional_items", 0)
                      - values.get("share_of_associates", 0)
                      + values.get("finance_costs", 0) + values.get("depreciation", 0)
                      - values.get("other_income", 0))
            # Revenue net of excise (e.g. ITC: excise is a pass-through tax that
            # can swing gross revenue by 40%+ without any real change in sales)
            revenue = values.get("revenue", 0) - values.get("excise_duty", 0)
            metrics = {
                "Revenue": revenue,
                "EBITDA": ebitda,
                "PBT": values.get("pbt", 0),
                "PAT": values.get("pat", 0),
            }
        periods.append({"label": p.get("label"), "metrics": metrics,
                        "exceptional": values.get("exceptional_items", 0),
                        "excise": values.get("excise_duty", 0)})
    return periods


def build_card(symbol, announcement_id, pdf_url):
    doc = pymupdf.open(get_pdf_path(pdf_url))
    bank = is_bank(doc)
    page_index = find_pl_page(doc, bank)
    if page_index is not None:
        images = [doc[page_index].get_pixmap(dpi=150).tobytes("png")]
        page_number = page_index + 1
    else:
        # Scanned filing with no text layer (e.g. Deepak Nitrite): we can't pick the
        # page by keywords, so send the first few text-less pages and let the model find it.
        images = []
        for i in range(len(doc)):
            if len(doc[i].get_text().strip()) < 50 and len(images) < MAX_SCANNED_PAGES:
                images.append(doc[i].get_pixmap(dpi=110).tobytes("png"))
        page_number = "scanned"
        if len(images) == 0:
            doc.close()
            return {"symbol": symbol, "error": "no P&L page found"}
    doc.close()

    if bank:
        prompt = BANK_PROMPT
    else:
        prompt = COMPANY_PROMPT.format(statement="CONSOLIDATED (or standalone if that is all there is)")
    if len(images) > 1:
        prompt = "The images are several pages of a filing; find the profit and loss table among them.\n" + prompt
    answer = call_llm(prompt, json_output=True, purpose="results_card", images=images)
    raw = json.loads(answer)
    if isinstance(raw, list):          # some models wrap the object in a list
        raw = raw[0]

    periods = build_metrics(raw, bank)
    current = periods[0]
    previous = periods[1]
    year_ago = periods[2]

    rows = []
    for name in current["metrics"]:
        value = current["metrics"][name]
        rows.append({
            "metric": name,
            "value_cr": round(value, 1),
            "qoq_pct": pct_change(value, previous["metrics"][name]),
            "yoy_pct": pct_change(value, year_ago["metrics"][name]),
        })

    card = {
        "symbol": symbol,
        "announcement_id": announcement_id,
        "type": "bank" if bank else "company",
        "statement": raw.get("statement"),
        "unit_in_pdf": raw.get("unit"),
        "page": page_number,
        "periods": [current["label"], previous["label"], year_ago["label"]],
        "rows": rows,
        "raw_periods": periods,
        "pdf_url": pdf_url,
    }
    notes = []
    if current["excise"] != 0:
        notes.append("Revenue is shown net of excise duty (Rs " + str(round(current["excise"], 1))
                     + " cr this quarter).")
    if current["exceptional"] != 0:
        notes.append("Includes an exceptional item of Rs " + str(round(current["exceptional"], 1))
                     + " cr this quarter (in PBT/PAT).")
    if len(notes) > 0:
        card["note"] = " ".join(notes)
    return card


def find_results_filing(symbol):
    """The main results filing for a symbol: the board-meeting outcome with the results."""
    conn = get_conn()
    row = conn.execute(
        "SELECT id, pdf_url FROM announcements WHERE symbol = ? AND category = 'results' "
        "AND subject = 'Outcome of Board Meeting' AND details LIKE '%financial results%' "
        "ORDER BY datetime DESC", (symbol,)).fetchone()
    conn.close()
    return row


def save_card(card):
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO results_cards VALUES (?, ?, ?)",
                 (card["announcement_id"], card["symbol"], json.dumps(card)))
    conn.commit()
    conn.close()


def format_pct(value):
    if value is None:
        return "   n/a"
    sign = "+" if value >= 0 else ""
    return (sign + str(value) + "%").rjust(7)


def print_card(card):
    print("\n==========", card["symbol"], "results (" + str(card["statement"]) + ", Rs crore) ==========")
    print("Quarters:", card["periods"][0], "| vs", card["periods"][1], "(QoQ) | vs", card["periods"][2], "(YoY)")
    print("PDF page", card["page"], "| unit in PDF:", card["unit_in_pdf"])
    print("Metric".ljust(22), "Value".rjust(12), "QoQ".rjust(8), "YoY".rjust(8))
    for row in card["rows"]:
        print(row["metric"].ljust(22), ("{:,.1f}".format(row["value_cr"])).rjust(12),
              format_pct(row["qoq_pct"]), format_pct(row["yoy_pct"]))
    if card.get("note"):
        print("Note:", card["note"])


if __name__ == "__main__":
    symbols = sys.argv[1:]
    if len(symbols) == 0:
        symbols = ["TCS", "ITC", "SBIN"]
    for symbol in symbols:
        filing = find_results_filing(symbol)
        if filing is None:
            print("No results filing in the DB for", symbol)
            continue
        card = build_card(symbol, filing[0], filing[1])
        if "error" in card:
            print(symbol, "->", card["error"])
            continue
        save_card(card)
        print_card(card)
