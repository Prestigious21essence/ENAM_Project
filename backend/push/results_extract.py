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
CARD_MODELS = ["gemini-3.5-flash", "gemini-3.8-flash", "gemini-3.5-flash-lite"]

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
   "revenue_lines": [the number(s) for Revenue from operations: its total line if printed, otherwise EACH line under it, e.g. sale of products and other operating revenues],
   "other_income_lines": [every OTHER line that is added into Total income: 'Other income' and any one-off income such as fair value gains. Not other operating revenue],
   "total_income": "Total income as printed",
   "excise_duty": "Excise duty (an expense line; 0 if none)",
   "share_of_associates": "Share of profit/(loss) of associates and joint ventures (0 if none)",
   "finance_costs": "Finance costs",
   "depreciation": "Depreciation and amortisation",
   "pbt_before_exceptional": "Profit before exceptional items and tax (same as pbt if there is no such line)",
   "exceptional_items": "Exceptional items, positive if it ADDS to profit, negative if a loss (an expense or charge is negative)",
   "pbt": "Profit before tax",
   "total_tax": "Total tax expense",
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
            if key == "label":
                continue
            if isinstance(p[key], list):
                # the model copies lines, Python adds them up
                total = 0.0
                for item in p[key]:
                    total = total + to_number(item)
                values[key] = total * factor
            else:
                values[key] = to_number(p[key]) * factor
        # names used below
        if "revenue_lines" in values:
            values["revenue"] = values["revenue_lines"]
        if "other_income_lines" in values:
            values["other_income"] = values["other_income_lines"]

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
            # Some companies (e.g. Sun Pharma) add the associates' share AFTER tax
            # (PAT = PBT - tax + associates), so it isn't inside PBT: leave it out then.
            # When PAT = PBT - tax exactly we can't tell from the numbers whether the
            # share sits inside PBT (ITC) or below PAT (Reliance), so keep the formula.
            pbt = values.get("pbt", 0)
            tax = values.get("total_tax", 0)
            pat = values.get("pat", 0)
            associates = values.get("share_of_associates", 0)
            if tax != 0 and associates != 0 and abs(pbt - tax - pat) > 1.0 \
                    and abs(pbt - tax + associates - pat) <= 1.0:
                associates = 0
            ebitda = (pbt - values.get("exceptional_items", 0) - associates
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
        problems = []
        if not bank:
            problems = check_period(values, metrics)
        periods.append({"label": p.get("label"), "metrics": metrics,
                        "exceptional": values.get("exceptional_items", 0),
                        "excise": values.get("excise_duty", 0),
                        "problems": problems})
    return periods


def close_enough(a, b, base):
    return abs(a - b) <= max(0.01 * abs(base), 1.0)


def check_period(values, metrics):
    """Accounting identities that must hold on any P&L. A failure means a number was misread."""
    problems = []
    pbt = values.get("pbt", 0)
    pat = values.get("pat", 0)

    # 1. revenue + other income = total income
    if values.get("total_income", 0) > 0:
        if not close_enough(values.get("revenue", 0) + values.get("other_income", 0), values["total_income"], values["total_income"]):
            problems.append("revenue + other income != total income")

    # 2. profit before exceptional items + exceptional items = PBT (catches sign errors)
    if values.get("pbt_before_exceptional", 0) != 0:
        if not close_enough(values["pbt_before_exceptional"] + values.get("exceptional_items", 0), pbt, pbt):
            problems.append("PBT before exceptional + exceptional != PBT")

    # 3. PBT - tax = PAT (some companies add their associates' share after tax)
    if values.get("total_tax", 0) != 0:
        after_tax = pbt - values["total_tax"]
        with_associates = after_tax + values.get("share_of_associates", 0)
        if not close_enough(after_tax, pat, pbt) and not close_enough(with_associates, pat, pbt):
            problems.append("PBT - tax != PAT")

    # 4. a profitable company can't have negative EBITDA
    if pbt > 0 and metrics["EBITDA"] <= 0:
        problems.append("EBITDA <= 0 while PBT > 0")
    return problems


# Which headline numbers each failed check makes unreliable
AFFECTED_BY = {
    "revenue + other income != total income": ["Revenue", "EBITDA"],
    "PBT before exceptional + exceptional != PBT": ["EBITDA", "PBT"],
    "PBT - tax != PAT": ["PBT", "PAT"],
    "EBITDA <= 0 while PBT > 0": ["EBITDA"],
}


def affected_metrics(period):
    names = []
    for problem in period.get("problems", []):
        names.extend(AFFECTED_BY.get(problem, []))
    return names


def count_problems(periods):
    total = 0
    for p in periods:
        total = total + len(p["problems"])
    return total


def build_card(symbol, announcement_id, pdf_url):
    doc = pymupdf.open(get_pdf_path(pdf_url))
    bank = is_bank(doc)
    page_index = find_pl_page(doc, bank)
    if page_index is not None:
        images = [doc[page_index].get_pixmap(dpi=200).tobytes("png")]
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
    # Numbers matter most here. Ask one model at a time; if its reading fails the
    # accounting checks, ask the next model. Keep the first clean reading (or the
    # reading with the fewest problems if none is clean).
    best = None
    tried = []
    for model in CARD_MODELS:
        try:
            answer = call_llm(prompt, json_output=True, purpose="results_card", images=images, models=[model])
            raw = json.loads(answer)
        except Exception as e:
            print("  ", symbol, model, "gave no usable answer:", repr(e)[:80])
            continue
        if isinstance(raw, list):          # some models wrap the object in a list
            raw = raw[0]
        periods = build_metrics(raw, bank)
        problems = count_problems(periods)
        tried.append(model + " (" + str(problems) + " problems)")
        if best is None or problems < best["problems"]:
            best = {"raw": raw, "periods": periods, "problems": problems, "model": model}
        if problems == 0:
            break
    if best is None:
        raise RuntimeError("no model could read the results page")
    raw = best["raw"]
    periods = best["periods"]
    current = periods[0]
    previous = periods[1]
    year_ago = periods[2]

    rows = []
    for name in current["metrics"]:
        value = current["metrics"][name]
        qoq = pct_change(value, previous["metrics"][name])
        yoy = pct_change(value, year_ago["metrics"][name])
        # Never show a comparison built on a number that failed a check
        unverified = name in affected_metrics(current)
        if unverified or name in affected_metrics(previous):
            qoq = None
        if unverified or name in affected_metrics(year_ago):
            yoy = None
        rows.append({
            "metric": name,
            "value_cr": round(value, 1),
            "qoq_pct": qoq,
            "yoy_pct": yoy,
            "unverified": unverified,
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
        "read_by": best["model"],
        "models_tried": tried,
    }
    # If even the best reading breaks an accounting identity, say so on the card
    # instead of showing a possibly wrong number as fact.
    if not bank:
        card["self_check"] = "passed"
        for p in periods:
            if len(p["problems"]) > 0:
                card["self_check"] = "failed"
                card["warning"] = "Numbers for " + str(p["label"]) + " don't reconcile (" \
                                  + "; ".join(p["problems"]) + ") - check the PDF."

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
