"""Numeric research sections for any NSE ticker, from screener's tables. No LLM.

build_numbers("TCS") ->
  {"ticker", "name", "statement", "finance" (bank/NBFC layout?), "url", "fetched_on",
   "sections": [snapshot, trajectory, balance_sheet, cash_quality]}
  or None when screener doesn't know the ticker.

Each section: {"id", "title", "takeaway" (one line, from rules), "metrics": [...], "series"?}
Each metric:  {"label", "value" (number or "n/a"), "unit", "period",
               "source": {"table", "row", "column", "url"}}
All maths (CAGR, D/E, CFO/PAT, cumulative sums) is done here in Python.

Banks and NBFCs come in screener's finance layout (Revenue / Interest / Financing Profit,
no OPM, no working-capital days): those sections use what screener gives instead.

Usage:  python pull\\financials.py TCS HDFCBANK ASIANPAINT SHAILY
"""
import json
import os
import re
import sys

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from ingest.screener import get_company

NA = "n/a"


# ---------- small helpers (every one tolerates missing data) ----------

def fy_columns(table):
    """12-month financial-year columns of a P&L / cash-flow / ratios table: no TTM, and no
    changed-year-end columns such as screener's "Mar 2016 18m" (MRF), which would turn an
    18-month year into a fake growth jump."""
    columns = []
    for c in table["columns"]:
        if re.fullmatch(r"[A-Z][a-z]{2} \d{4}", c):
            columns.append(c)
    return columns


def column_year(column):
    try:
        return int(column.split()[1])
    except (IndexError, ValueError):
        return None


def cell(table, row, column):
    """One number from a parsed table, or None."""
    if row not in table["rows"] or column not in table["columns"]:
        return None
    index = table["columns"].index(column)
    values = table["rows"][row]
    if index >= len(values):
        return None
    return values[index]


def latest_value(table, row):
    """(column, value) of the newest non-missing cell in a row; (None, None) if none."""
    if row not in table["rows"]:
        return None, None
    values = table["rows"][row]
    for i in range(min(len(values), len(table["columns"])) - 1, -1, -1):
        if values[i] is not None:
            return table["columns"][i], values[i]
    return None, None


def value_or_na(x, digits=1):
    if x is None:
        return NA
    return round(x, digits)


def metric(label, value, unit, period, table, row, column, url, digits=1):
    return {"label": label, "value": value_or_na(value, digits), "unit": unit, "period": period,
            "source": {"table": table, "row": row, "column": column, "url": url}}


def pct(new, old):
    if new is None or old is None or old == 0:
        return None
    return round((new - old) / abs(old) * 100, 1)


def cagr(series_end, series_start, years):
    """Compound annual growth, as a percent. None if either end is missing or not positive."""
    if series_end is None or series_start is None or series_start <= 0 or series_end <= 0 or years <= 0:
        return None
    return round(((series_end / series_start) ** (1.0 / years) - 1) * 100, 1)


def ratio(a, b, digits=2):
    if a is None or b is None or b == 0:
        return None
    return round(a / b, digits)


def fy_label(column):
    """'Mar 2026' -> 'FY26'."""
    if column is None:
        return NA
    parts = column.split()
    if len(parts) == 2 and parts[1].isdigit():
        return "FY" + parts[1][-2:]
    return column


def direction(values, flat_band):
    """'rising' / 'falling' / 'stable' from the first to the last non-missing value."""
    clean = [v for v in values if v is not None]
    if len(clean) < 2:
        return None
    change = clean[-1] - clean[0]
    if change > flat_band:
        return "rising"
    if change < -flat_band:
        return "falling"
    return "stable"


# ---------- section 1: snapshot ----------

def build_snapshot(c, finance):
    pl = c["profit_loss"]
    url = c["url"]
    years = fy_columns(pl)
    fy = years[-1] if years else None
    ttm = "TTM" if "TTM" in pl["columns"] else None
    fy_name = fy_label(fy)
    sales_row = "Revenue" if finance else "Sales"
    metrics = []
    for column, period in [(fy, fy_name), (ttm, "TTM")]:
        if column is None:
            continue
        metrics.append(metric("Interest earned" if finance else "Revenue", cell(pl, sales_row, column), "Rs cr", period, "profit_loss", sales_row, column, url, 0))
        if finance:
            # screener's "Financing Margin %" is its own construct (negative for HDFC Bank after
            # the merger) and would mislead a reader, so it is not shown.
            metrics.append(metric("Net interest income", nii_value(pl, column), "Rs cr", period, "profit_loss", "Revenue - Interest", column, url, 0))
        else:
            metrics.append(metric("Operating margin (OPM)", cell(pl, "OPM %", column), "%", period, "profit_loss", "OPM %", column, url))
        metrics.append(metric("Net profit (PAT)", cell(pl, "Net Profit", column), "Rs cr", period, "profit_loss", "Net Profit", column, url, 0))

    # ROE: banks have a yearly row; companies only have screener's top-of-page figure
    roe = cell(c["ratios"], "ROE %", fy) if finance else None
    if roe is not None:
        metrics.append(metric("ROE", roe, "%", fy_name, "ratios", "ROE %", fy, url))
    else:
        metrics.append(metric("ROE", c["top_ratios"].get("ROE"), "%", "latest", "top_ratios", "ROE", "latest", url))
    if not finance:
        roce = cell(c["ratios"], "ROCE %", fy)
        if roce is not None:
            metrics.append(metric("ROCE", roce, "%", fy_name, "ratios", "ROCE %", fy, url))
        else:
            metrics.append(metric("ROCE", c["top_ratios"].get("ROCE"), "%", "latest", "top_ratios", "ROCE", "latest", url))

    # takeaway from rules
    sales_fy = cell(pl, sales_row, fy)
    sales_ttm = cell(pl, sales_row, ttm) if ttm else None
    pat_fy = cell(pl, "Net Profit", fy)
    pat_ttm = cell(pl, "Net Profit", ttm) if ttm else None
    roe_value = roe if roe is not None else c["top_ratios"].get("ROE")
    parts = []
    if sales_fy is not None:
        parts.append(fy_name + (" interest earned Rs " if finance else " revenue Rs ") + "{:,.0f}".format(sales_fy) + " cr")
        if sales_ttm is not None and pct(sales_ttm, sales_fy) is not None:
            parts[-1] = parts[-1] + ", TTM " + signed(pct(sales_ttm, sales_fy)) + "% vs " + fy_name
    if pat_fy is not None:
        text = "PAT Rs " + "{:,.0f}".format(pat_fy) + " cr"
        if pat_ttm is not None and pct(pat_ttm, pat_fy) is not None:
            text = text + " (TTM " + signed(pct(pat_ttm, pat_fy)) + "%)"
        parts.append(text)
    if roe_value is not None:
        if roe_value >= 20:
            parts.append("ROE " + str(roe_value) + "%: high-return business")
        elif roe_value >= 10:
            parts.append("ROE " + str(roe_value) + "%: moderate returns")
        else:
            parts.append("ROE " + str(roe_value) + "%: low returns on equity")
    takeaway = "; ".join(parts) if parts else "No P&L data on screener."
    return {"id": "snapshot", "title": "Financial snapshot", "takeaway": takeaway, "metrics": metrics}


def signed(x):
    if x is None:
        return NA
    return ("+" if x >= 0 else "") + str(x)


def nii_value(pl, column):
    """Net interest income = screener's Revenue (interest earned) - Interest (expended)."""
    revenue = cell(pl, "Revenue", column)
    interest = cell(pl, "Interest", column)
    if revenue is None or interest is None:
        return None
    return revenue - interest


def biggest_jump(years, values, window=5):
    """(FY column, growth %) of the largest one-year rise inside the CAGR window (the last
    `window` years), counting only pairs of consecutive 12-month years."""
    best_year = None
    best_pct = None
    start = max(1, len(values) - window)
    for i in range(start, len(values)):
        y_now, y_prev = column_year(years[i]), column_year(years[i - 1])
        if y_now is None or y_prev is None or y_now - y_prev != 1:
            continue
        growth = pct(values[i], values[i - 1])
        if growth is not None and (best_pct is None or growth > best_pct):
            best_year = years[i]
            best_pct = growth
    return best_year, best_pct


def cagr_over(years, values, n):
    """CAGR over exactly n years of 12-month columns; None if the span isn't exactly n years."""
    if len(years) <= n:
        return None
    end_year, start_year = column_year(years[-1]), column_year(years[-1 - n])
    if end_year is None or start_year is None or end_year - start_year != n:
        return None
    return cagr(values[-1], values[-1 - n], n)


# ---------- section 2: trajectory ----------

def build_trajectory(c, finance):
    pl = c["profit_loss"]
    url = c["url"]
    years = fy_columns(pl)
    sales_row = "Revenue" if finance else "Sales"
    sales_label = "Interest earned" if finance else "Revenue"
    sales = [cell(pl, sales_row, y) for y in years]
    profit = [cell(pl, "Net Profit", y) for y in years]
    # Finance companies: NII instead of a margin (screener's financing margin misleads)
    nii = [nii_value(pl, y) for y in years] if finance else None
    margin = None if finance else [cell(pl, "OPM %", y) for y in years]
    metrics = []
    for n in (3, 5):
        if len(years) > n:
            end, start = years[-1], years[-1 - n]
            span = start + " to " + end
            metrics.append(metric(sales_label + " CAGR " + str(n) + "y", cagr_over(years, sales, n), "%", span, "profit_loss", sales_row, span, url))
            if finance:
                metrics.append(metric("NII CAGR " + str(n) + "y", cagr_over(years, nii, n), "%", span, "profit_loss", "Revenue - Interest", span, url))
            metrics.append(metric("Profit CAGR " + str(n) + "y", cagr_over(years, profit, n), "%", span, "profit_loss", "Net Profit", span, url))
        else:
            metrics.append(metric(sales_label + " CAGR " + str(n) + "y", None, "%", "needs " + str(n + 1) + " years", "profit_loss", sales_row, NA, url))
            if finance:
                metrics.append(metric("NII CAGR " + str(n) + "y", None, "%", "needs " + str(n + 1) + " years", "profit_loss", "Revenue - Interest", NA, url))
            metrics.append(metric("Profit CAGR " + str(n) + "y", None, "%", "needs " + str(n + 1) + " years", "profit_loss", "Net Profit", NA, url))
    margin_dir = None
    if not finance:
        margin_dir = direction(margin[-3:], 1.0)
        span3 = (years[-3] + " to " + years[-1]) if len(years) >= 3 else NA
        metrics.append({"label": "Margin direction (OPM, 3 yrs)", "value": margin_dir if margin_dir else NA, "unit": "",
                        "period": span3, "source": {"table": "profit_loss", "row": "OPM %", "column": span3, "url": url}})
        metrics.append(metric("Latest OPM", margin[-1] if margin else None, "%", fy_label(years[-1]) if years else NA, "profit_loss", "OPM %", years[-1] if years else NA, url))

    # A one-year jump of more than 40% is usually an acquisition or merger, not organic growth
    jump_year, jump_pct = biggest_jump(years, sales)
    jump_note = None
    if jump_pct is not None and jump_pct > 40:
        jump_note = ("includes a one-year jump of " + str(jump_pct) + "% in " + fy_label(jump_year)
                     + " (acquisition or merger?): check the annual report")
        metrics.append(metric("One-year " + sales_label.lower() + " jump", jump_pct, "%", fy_label(jump_year), "profit_loss", sales_row, jump_year, url))

    # takeaway
    s5 = cagr_over(years, sales, 5)
    p5 = cagr_over(years, profit, 5)
    s3 = cagr_over(years, sales, 3)
    p3 = cagr_over(years, profit, 3)
    horizon, s, p = (5, s5, p5) if s5 is not None else (3, s3, p3)
    parts = []
    if s is not None:
        parts.append(sales_label + " grew " + str(s) + "% a year over " + str(horizon) + " years")
        if finance and len(years) > horizon:
            n_cagr = cagr_over(years, nii, horizon)
            if n_cagr is not None:
                parts.append("NII " + str(n_cagr) + "% a year")
        if p is not None:
            parts.append("profit " + str(p) + "% a year")
            if p > s + 2:
                parts.append("profit outpacing " + sales_label.lower())
            elif p < s - 2:
                parts.append("profit lagging " + sales_label.lower())
    elif p is not None:
        parts.append("Profit grew " + str(p) + "% a year over " + str(horizon) + " years")
    if margin_dir is not None:
        parts.append("margins " + margin_dir + " over 3 years")
    if jump_note is not None:
        parts.append(jump_note)
    takeaway = "; ".join(parts) if parts else "Not enough yearly data for a trend."
    series = {"years": [fy_label(y) for y in years], "revenue": sales, "revenue_name": sales_label,
              "net_profit": profit, "source": {"table": "profit_loss", "url": url}}
    if finance:
        series["nii"] = nii
    else:
        series["margin_pct"] = margin
        series["margin_name"] = "OPM %"
    return {"id": "trajectory", "title": "Trajectory", "takeaway": takeaway, "metrics": metrics, "series": series}


# ---------- section 3: balance sheet ----------

def build_balance_sheet(c, finance):
    bs = c["balance_sheet"]
    ra = c["ratios"]
    url = c["url"]
    latest = bs["columns"][-1] if bs["columns"] else None       # often a half-year, e.g. Sep 2026
    ratio_years = fy_columns(ra)
    ratio_fy = ratio_years[-1] if ratio_years else None
    borrow_row = "Borrowing" if "Borrowing" in bs["rows"] else "Borrowings"
    borrowings = cell(bs, borrow_row, latest)
    equity = None
    if cell(bs, "Equity Capital", latest) is not None and cell(bs, "Reserves", latest) is not None:
        equity = cell(bs, "Equity Capital", latest) + cell(bs, "Reserves", latest)
    metrics = [
        metric("Borrowings", borrowings, "Rs cr", latest, "balance_sheet", borrow_row, latest, url, 0),
        metric("Net worth (equity + reserves)", equity, "Rs cr", latest, "balance_sheet", "Equity Capital + Reserves", latest, url, 0),
    ]
    parts = []
    if finance:
        deposits = cell(bs, "Deposits", latest)
        if deposits is not None:
            metrics.insert(0, metric("Deposits", deposits, "Rs cr", latest, "balance_sheet", "Deposits", latest, url, 0))
        # NPA rows are filled only on the STANDALONE page (consolidated shows blanks)
        q = c["quarters"]
        npa_url = url
        gcol, gnpa = latest_value(q, "Gross NPA %")
        if gnpa is None and c["statement"] == "consolidated":
            standalone = get_company(c["ticker"], statement="standalone")
            if standalone is not None:
                q = standalone["quarters"]
                npa_url = standalone["url"]
                gcol, gnpa = latest_value(q, "Gross NPA %")
        ncol, nnpa = latest_value(q, "Net NPA %")
        metrics.append(metric("Gross NPA", gnpa, "%", gcol or NA, "quarters (standalone)", "Gross NPA %", gcol, npa_url, 2))
        metrics.append(metric("Net NPA", nnpa, "%", ncol or NA, "quarters (standalone)", "Net NPA %", ncol, npa_url, 2))
        lev = ratio(cell(bs, "Total Assets", latest), equity, 1)
        metrics.append(metric("Assets / net worth (leverage)", lev, "x", latest, "balance_sheet", "Total Assets / (Equity Capital + Reserves)", latest, url))
        if gnpa is not None:
            if gnpa < 1.5:
                parts.append("Gross NPA " + str(gnpa) + "%: clean loan book")
            elif gnpa < 4:
                parts.append("Gross NPA " + str(gnpa) + "%: moderate stress")
            else:
                parts.append("Gross NPA " + str(gnpa) + "%: high stress")
        if lev is not None:
            parts.append("balance sheet " + str(lev) + "x net worth")
        if not parts:
            parts.append("Finance company: debt/equity and working-capital days don't apply")
    else:
        de = ratio(borrowings, equity)
        metrics.append(metric("Debt / equity", de, "x", latest, "balance_sheet", borrow_row + " / (Equity Capital + Reserves)", latest, url))
        for label, row in [("Debtor days", "Debtor Days"), ("Inventory days", "Inventory Days"),
                           ("Days payable", "Days Payable"), ("Cash conversion cycle", "Cash Conversion Cycle")]:
            metrics.append(metric(label, cell(ra, row, ratio_fy), "days", fy_label(ratio_fy), "ratios", row, ratio_fy, url, 0))
        if de is not None:
            if de < 0.3:
                parts.append("Debt/equity " + str(de) + "x: nearly debt-free")
            elif de < 1:
                parts.append("Debt/equity " + str(de) + "x: moderate leverage")
            else:
                parts.append("Debt/equity " + str(de) + "x: leveraged")
        ccc_now = cell(ra, "Cash Conversion Cycle", ratio_fy)
        ccc_then = cell(ra, "Cash Conversion Cycle", ratio_years[-4]) if len(ratio_years) >= 4 else None
        if ccc_now is not None:
            text = "cash conversion cycle " + str(int(ccc_now)) + " days"
            if ccc_then is not None:
                if ccc_now > ccc_then + 10:
                    text = text + ", lengthening (was " + str(int(ccc_then)) + " three years ago)"
                elif ccc_now < ccc_then - 10:
                    text = text + ", shortening (was " + str(int(ccc_then)) + " three years ago)"
                else:
                    text = text + ", steady"
            parts.append(text)
    takeaway = "; ".join(parts) if parts else "No balance-sheet data on screener."
    return {"id": "balance_sheet", "title": "Balance sheet", "takeaway": takeaway, "metrics": metrics}


# ---------- section 4: cash quality ----------

def build_cash_quality(c, finance):
    cf = c["cash_flow"]
    pl = c["profit_loss"]
    url = c["url"]
    years = fy_columns(cf)[-5:]
    metrics = []
    series = {"years": [], "cfo": [], "pat": [], "cfo_to_pat": [], "fcf": []}
    sum_cfo = 0.0
    sum_pat = 0.0
    n_years = 0
    for y in years:
        cfo = cell(cf, "Cash from Operating Activity", y)
        pat = cell(pl, "Net Profit", y)
        fcf = cell(cf, "Free Cash Flow", y)
        series["years"].append(fy_label(y))
        series["cfo"].append(cfo)
        series["pat"].append(pat)
        series["cfo_to_pat"].append(ratio(cfo, pat))
        series["fcf"].append(fcf)
        if cfo is not None and pat is not None:
            sum_cfo = sum_cfo + cfo
            sum_pat = sum_pat + pat
            n_years = n_years + 1
        metrics.append(metric("CFO / PAT", ratio(cfo, pat), "x", fy_label(y), "cash_flow + profit_loss",
                              "Cash from Operating Activity / Net Profit", y, url, 2))
    span = (years[0] + " to " + years[-1]) if years else NA
    cumulative = ratio(sum_cfo, sum_pat) if n_years > 0 else None
    metrics.append(metric("CFO / PAT, cumulative " + str(n_years) + " yrs", cumulative, "x", span, "cash_flow + profit_loss",
                          "sum(Cash from Operating Activity) / sum(Net Profit)", span, url, 2))
    latest = years[-1] if years else None
    fcf_latest = cell(cf, "Free Cash Flow", latest)
    metrics.append(metric("Free cash flow", fcf_latest, "Rs cr", fy_label(latest), "cash_flow", "Free Cash Flow", latest, url, 0))
    fcf_values = [v for v in series["fcf"] if v is not None]
    metrics.append(metric("Free cash flow, cumulative " + str(len(fcf_values)) + " yrs", sum(fcf_values) if fcf_values else None,
                          "Rs cr", span, "cash_flow", "Free Cash Flow", span, url, 0))
    if "CFO/EBITDA" in cf["rows"]:
        metrics.append(metric("CFO / EBITDA (screener)", cell(cf, "CFO/EBITDA", latest), "%", fy_label(latest), "cash_flow", "CFO/EBITDA", latest, url, 0))

    parts = []
    if finance:
        parts.append("Operating cash flow is not a quality measure for a lender (deposits and loans flow through it)")
        if fcf_values:
            parts.append("shown as screener reports it")
    else:
        if cumulative is not None:
            if cumulative >= 0.9:
                parts.append("Profits convert to cash: " + str(n_years) + "-yr CFO/PAT " + str(cumulative) + "x")
            elif cumulative >= 0.6:
                parts.append("Partial cash conversion: " + str(n_years) + "-yr CFO/PAT " + str(cumulative) + "x")
            else:
                parts.append("Weak cash conversion: " + str(n_years) + "-yr CFO/PAT " + str(cumulative) + "x")
        negatives = len([v for v in fcf_values if v < 0])
        if fcf_values:
            if negatives == 0:
                parts.append("free cash flow positive every year")
            else:
                parts.append("free cash flow negative in " + str(negatives) + " of " + str(len(fcf_values)) + " years")
    takeaway = "; ".join(parts) if parts else "No cash-flow data on screener."
    return {"id": "cash_quality", "title": "Cash quality", "takeaway": takeaway, "metrics": metrics, "series": series}


# ---------- put together ----------

def is_finance_layout(company):
    """Banks and NBFCs: screener shows Revenue / Interest / Financing Profit, no OPM."""
    rows = company["profit_loss"]["rows"]
    return "Financing Profit" in rows or ("Revenue" in rows and "Sales" not in rows)


def build_numbers(ticker):
    company = get_company(ticker)
    if company is None:
        return None
    finance = is_finance_layout(company)
    sections = []
    for build in (build_snapshot, build_trajectory, build_balance_sheet, build_cash_quality):
        try:
            sections.append(build(company, finance))
        except Exception as e:              # a strange page must never kill the research
            sections.append({"id": build.__name__.replace("build_", ""), "title": build.__name__.replace("build_", "").replace("_", " ").title(),
                             "takeaway": "Could not compute this section: " + repr(e)[:80], "metrics": []})
    return {"ticker": company["ticker"], "name": company["name"], "statement": company["statement"],
            "finance": finance, "url": company["url"], "fetched_on": company["fetched_on"],
            "screener_cagr": company.get("growth", {}), "sections": sections}


def print_numbers(result):
    print("\n==========", result["ticker"], "|", result["name"], "|", result["statement"],
          "|", "finance layout" if result["finance"] else "company layout", "==========")
    for section in result["sections"]:
        print("\n--", section["title"], "--")
        print("   >>", section["takeaway"])
        for m in section["metrics"]:
            value = m["value"]
            if isinstance(value, float) and abs(value) >= 1000:
                value = "{:,.0f}".format(value)
            print("   " + m["label"].ljust(40), str(value).rjust(12), m["unit"].ljust(6), "|", str(m["period"]).ljust(22),
                  "| src:", m["source"]["table"] + " / " + m["source"]["row"] + " / " + str(m["source"]["column"]))
        if "series" in section and "revenue" in section["series"]:
            s = section["series"]
            third = s["nii"] if "nii" in s else s["margin_pct"]
            print("   series (year, " + s["revenue_name"].lower() + ", profit, " + ("nii" if "nii" in s else "opm") + "):",
                  list(zip(s["years"], s["revenue"], s["net_profit"], third)))
    g = result["screener_cagr"]
    if g:
        print("\n   screener's own CAGR boxes (for checking):", {k: g[k] for k in g if "Growth" in k})


if __name__ == "__main__":
    for symbol in sys.argv[1:] or ["TCS"]:
        result = build_numbers(symbol)
        if result is None:
            print("\n", symbol, "-> not found on screener")
            continue
        print_numbers(result)
        if "--json" in sys.argv:
            print(json.dumps(result, indent=1))
