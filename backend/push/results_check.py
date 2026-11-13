"""Cross-check every results card against screener.in's quarterly table.

Like with like:
  companies  card statement (consolidated / standalone) -> same screener page;
             Revenue vs screener "Sales", PAT vs "Net Profit"
  banks      cards are standalone -> screener standalone page;
             NII vs "Revenue" - "Interest", PAT vs "Net Profit"
Also compared (information only): EBITDA vs "Operating Profit", PBT vs "Profit before tax".

Anything more than 2% off is flagged. The result is saved on the card
(card["screener_check"]) so the app can show it, and printed as a table.

Usage:  python push\\results_check.py            (all cards)
        python push\\results_check.py TCS ITC     (some symbols)
"""
import json
import os
import re
import sys
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from db import get_conn
from ingest.screener import get_company

TOLERANCE_PCT = 2.0

DATE_FORMATS = ["%B %d %Y", "%d %B %Y", "%d/%m/%Y", "%d.%m.%Y", "%d-%m-%Y", "%d-%b-%y", "%d %b %y",
                "%d-%b-%Y", "%d %b %Y", "%B %d %y", "%b %d %Y"]


def quarter_column(label):
    """Card quarter label -> screener column, e.g. "30th Sep'26" -> "Sep 2026"."""
    text = str(label).replace("'", " 20").replace(",", " ")
    text = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", text)
    text = " ".join(text.split())
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).strftime("%b %Y")
        except ValueError:
            continue
    return None


def diff_pct(card_value, screener_value):
    if card_value is None or screener_value is None or screener_value == 0:
        return None
    return round((card_value - screener_value) / abs(screener_value) * 100, 1)


def screener_values(card):
    """The screener column that matches this card: (statement, quarter, {row: value}) or an error."""
    bank = card["type"] == "bank"
    statement = "standalone" if bank else (card.get("statement") or "consolidated")
    if statement not in ("consolidated", "standalone"):
        statement = "consolidated"
    company = get_company(card["symbol"], statement=statement)
    if company is None:
        return None, None, None, "not on screener"
    quarter = quarter_column(card["periods"][0])
    columns = company["quarters"]["columns"]
    if quarter is None or quarter not in columns:
        return company, statement, None, "quarter " + str(card["periods"][0]) + " not in screener (" + str(columns[-1:]) + ")"
    index = columns.index(quarter)
    values = {}
    for name in company["quarters"]["rows"]:
        values[name] = company["quarters"]["rows"][name][index]
    return company, statement, quarter, values


def check_card(card):
    """Return card["screener_check"]: per-metric card vs screener numbers, and a status."""
    company, statement, quarter, values = screener_values(card)
    if quarter is None:
        return {"status": "no data", "note": values}
    bank = card["type"] == "bank"
    card_values = {}
    for row in card["rows"]:
        card_values[row["metric"]] = row["value_cr"]

    if bank:
        revenue_s = None
        if values.get("Revenue") is not None and values.get("Interest") is not None:
            revenue_s = values["Revenue"] - values["Interest"]
        pairs = [("Net interest income", "Revenue - Interest", revenue_s),
                 ("Operating profit", "Financing Profit + Other Income - Depreciation", None),
                 ("PBT", "Profit before tax", values.get("Profit before tax")),
                 ("PAT", "Net Profit", values.get("Net Profit"))]
    else:
        # NBFCs (e.g. Bajaj Finance) get screener's finance layout: "Revenue", no "Sales"
        sales_row = "Sales" if "Sales" in values else "Revenue"
        pairs = [("Revenue", sales_row, values.get(sales_row)),
                 ("EBITDA", "Operating Profit", values.get("Operating Profit")),
                 ("PBT", "Profit before tax", values.get("Profit before tax")),
                 ("PAT", "Net Profit", values.get("Net Profit"))]

    metrics = {}
    flagged = []
    for card_name, screener_name, screener_value in pairs:
        card_value = card_values.get(card_name)
        d = diff_pct(card_value, screener_value)
        metrics[card_name] = {"card": card_value, "screener_row": screener_name,
                              "screener": screener_value, "diff_pct": d}
        # Revenue and PAT decide the status; EBITDA/PBT definitions differ, so they only inform.
        headline = card_name in ("Revenue", "Net interest income", "PAT")
        if headline and (d is None or abs(d) > TOLERANCE_PCT):
            flagged.append(card_name)

    # A company card read from a standalone page while consolidated statements exist
    note = None
    if not bank and statement == "standalone" and company.get("consolidated_available"):
        note = "card was read from the STANDALONE statement; consolidated exists"
    # ITC-style excise: our revenue is net of excise, screener's Sales is gross
    excise = card.get("raw_periods", [{}])[0].get("excise", 0)
    if not bank and excise and "Revenue" in flagged and values.get("Sales") is not None:
        gross = card_values.get("Revenue", 0) + excise
        if abs(diff_pct(gross, values["Sales"]) or 99) <= TOLERANCE_PCT:
            flagged.remove("Revenue")
            metrics["Revenue"]["note"] = "matches gross of excise (" + str(round(gross, 1)) + ")"

    return {"status": "mismatch" if flagged else "ok", "flagged": flagged, "quarter": quarter,
            "statement": statement, "metrics": metrics, "note": note,
            "checked_on": datetime.now().strftime("%Y-%m-%d")}


def fmt(value):
    if value is None:
        return "n/a".rjust(10)
    return "{:,.0f}".format(value).rjust(10)


def fmt_pct(value):
    if value is None:
        return "   n/a"
    return ("{:+.1f}%".format(value)).rjust(6)


def run(symbols=None):
    conn = get_conn()
    query = "SELECT announcement_id, symbol, card FROM results_cards ORDER BY symbol"
    rows = conn.execute(query).fetchall()
    conn.close()
    n_ok = 0
    n_bad = 0
    print("symbol       stmt          quarter  | metric      card       screener  diff   | status")
    for announcement_id, symbol, card_json in rows:
        if symbols and symbol not in symbols:
            continue
        card = json.loads(card_json)
        if "rows" not in card:
            print(symbol.ljust(12), "no card (" + card.get("error", "?") + ")")
            continue
        check = check_card(card)
        card["screener_check"] = check
        conn = get_conn()
        conn.execute("UPDATE results_cards SET card = ? WHERE announcement_id = ?",
                     (json.dumps(card), announcement_id))
        conn.commit()
        conn.close()
        if check["status"] == "no data":
            print(symbol.ljust(12), "NO DATA:", check["note"])
            n_bad = n_bad + 1
            continue
        first = True
        for name in check["metrics"]:
            m = check["metrics"][name]
            flag = " <-- FLAG" if name in check["flagged"] else ""
            head = (symbol.ljust(12) + " " + check["statement"].ljust(12) + " " + check["quarter"]) if first else " " * 34
            print(head, "| " + name.ljust(10), fmt(m["card"]), fmt(m["screener"]), fmt_pct(m["diff_pct"]),
                  "|", (check["status"] if first else ""), flag, m.get("note", ""))
            first = False
        if check["note"]:
            print(" " * 34, "| note:", check["note"])
        if check["status"] == "ok":
            n_ok = n_ok + 1
        else:
            n_bad = n_bad + 1
    print("\n" + str(n_ok) + " cards match screener on revenue and PAT (within " + str(TOLERANCE_PCT) + "%), "
          + str(n_bad) + " flagged")


if __name__ == "__main__":
    run(sys.argv[1:] or None)
