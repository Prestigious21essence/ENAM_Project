"""screener.in for ANY NSE ticker: the financial tables + document links.

get_company("TCS") ->
  {"ticker", "name", "statement" ("consolidated" or "standalone"), "url", "fetched_on",
   "quarters", "profit_loss", "balance_sheet", "cash_flow", "ratios",   (tables, see below)
   "top_ratios": {"Market Cap": ..., "ROE": 51.8, "ROCE": 63.0, ...}   (the list at the top)
   "growth": {"Compounded Sales Growth": {"5 Years": 9.0, ...}, ...}   (screener's CAGR boxes)
   "documents": {"annual_reports": [{"year", "url", "source"}],
                 "concalls": [{"period", "transcript", "ppt", "rec"}]}}
  or None when screener has no such ticker (404).

A table = {"columns": ["Sep 2023", ...], "rows": {"Sales": [59692.0, ...], ...}}
Numbers are floats in Rs crore (percent rows are plain floats); blanks are None.

Only the tables and document links are read. Screener's own "About", "Pros/Cons",
AI summaries and notes are NOT primary sources and are ignored.

Consolidated figures first; standalone when the company has no consolidated statements
(screener then serves the same standalone numbers at both URLs and shows no
"View Standalone" link).

Raw HTML is cached on disk, one fetch per ticker per statement per day.

Usage:  python ingest\\screener.py TCS HDFCBANK ASIANPAINT
"""
import os
import re
import sys
import time
from datetime import date

import requests
from bs4 import BeautifulSoup

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "cache", "screener")
BASE_URL = "https://www.screener.in/company/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Accept-Language": "en-IN,en;q=0.9",
}
SECTIONS = {"quarters": "quarters", "profit_loss": "profit-loss", "balance_sheet": "balance-sheet",
            "cash_flow": "cash-flow", "ratios": "ratios"}
PAUSE_SECONDS = 1.0      # between live fetches: be polite, avoid a block

_last_fetch = 0.0


class NotFound(Exception):
    pass


# ---------- fetch (with a daily disk cache) ----------

def page_url(ticker, statement):
    if statement == "consolidated":
        return BASE_URL + ticker + "/consolidated/"
    return BASE_URL + ticker + "/"


def fetch_html(ticker, statement, use_cache=True):
    """Raw page HTML. Cached per ticker, statement and day. Raises NotFound on 404."""
    global _last_fetch
    ticker = ticker.upper().strip()
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache_path = os.path.join(CACHE_DIR, ticker + "_" + statement + "_" + date.today().isoformat() + ".html")
    if use_cache and os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8") as f:
            html = f.read()
        if html == "404":
            raise NotFound(ticker)
        return html

    wait = PAUSE_SECONDS - (time.time() - _last_fetch)
    if wait > 0:
        time.sleep(wait)
    response = requests.get(page_url(ticker, statement), headers=HEADERS, timeout=30)
    _last_fetch = time.time()
    if response.status_code == 404:
        with open(cache_path, "w", encoding="utf-8") as f:
            f.write("404")             # remember the miss too (no refetch today)
        raise NotFound(ticker)
    if response.status_code != 200:
        raise RuntimeError("screener " + str(response.status_code) + " for " + ticker)
    with open(cache_path, "w", encoding="utf-8") as f:
        f.write(response.text)
    return response.text


# ---------- parse ----------

def to_number(text):
    """'1,234' -> 1234.0 ; '-5,010' -> -5010.0 ; '+8%' -> 8.0 ; '' -> None"""
    text = text.replace(",", "").replace("%", "").replace("+", "").strip()
    if text == "" or text == "-":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def row_name(cell):
    """'Sales +' -> 'Sales'. Some cells carry a long explanation span; keep the first line."""
    button = cell.find("button")
    if button is not None:
        text = button.get_text(" ", strip=True)
    else:
        text = cell.get_text("\n", strip=True).split("\n")[0]
    return text.replace("\xa0", " ").rstrip(" +").strip()


def parse_table(table):
    header = table.find("thead")
    if header is None:
        return {"columns": [], "rows": {}}
    columns = []
    for th in header.find_all("th")[1:]:
        columns.append(th.get_text(" ", strip=True))
    rows = {}
    body = table.find("tbody") or table
    for tr in body.find_all("tr"):
        cells = tr.find_all("td")
        if len(cells) < 2:
            continue
        name = row_name(cells[0])
        if name == "" or name == "Raw PDF":
            continue
        values = []
        for td in cells[1:]:
            values.append(to_number(td.get_text(" ", strip=True)))
        rows[name] = values[:len(columns)]
    return {"columns": columns, "rows": rows}


def parse_documents(soup):
    docs = {"annual_reports": [], "concalls": []}
    section = soup.find("section", id="documents")
    if section is None:
        return docs
    reports = section.find("div", class_="annual-reports")
    if reports is not None:
        for li in reports.find_all("li"):
            a = li.find("a", href=True)
            if a is None:
                continue
            text = a.get_text(" ", strip=True)
            year = re.search(r"(20\d\d|19\d\d)", text)
            source = li.find("span")
            docs["annual_reports"].append({
                "year": int(year.group(1)) if year else None,
                "url": a["href"],
                "source": source.get_text(" ", strip=True).replace("from ", "") if source else None,
            })
    concalls = section.find("div", class_="concalls")
    if concalls is not None:
        for li in concalls.find_all("li"):
            period = li.find("div")
            item = {"period": period.get_text(" ", strip=True) if period else None,
                    "transcript": None, "ppt": None, "rec": None}
            for a in li.find_all("a", href=True):
                label = a.get_text(" ", strip=True).lower()
                if label in item:
                    item[label] = a["href"]
            if item["period"]:
                docs["concalls"].append(item)
    return docs


def parse_top_ratios(soup):
    """The list at the top of the page: {"Market Cap": 876040.0, "ROE": 51.8, "ROCE": 63.0, ...}."""
    ratios = {}
    block = soup.find("ul", id="top-ratios")
    if block is None:
        return ratios
    for li in block.find_all("li"):
        name = li.find("span", class_="name")
        number = li.find("span", class_="number")
        if name is None or number is None:
            continue
        ratios[name.get_text(" ", strip=True)] = to_number(number.get_text(" ", strip=True))
    return ratios


def parse_growth_tables(soup):
    """Screener's own CAGR mini-tables next to the P&L:
    {"Compounded Sales Growth": {"10 Years": 11.0, "5 Years": ..., "3 Years": ..., "TTM": ...},
     "Compounded Profit Growth": {...}, "Stock Price CAGR": {...}, "Return on Equity": {...}}"""
    growth = {}
    section = soup.find("section", id="profit-loss")
    if section is None:
        return growth
    for table in section.find_all("table", class_="ranges-table"):
        head = table.find("th")
        if head is None:
            continue
        values = {}
        for tr in table.find_all("tr"):
            cells = tr.find_all("td")
            if len(cells) == 2:
                values[cells[0].get_text(" ", strip=True).rstrip(":")] = to_number(cells[1].get_text(" ", strip=True))
        growth[head.get_text(" ", strip=True)] = values
    return growth


def has_consolidated(soup):
    """On the consolidated page a company with consolidated statements shows a
    'View Standalone' link; a standalone-only company shows no switch at all."""
    for a in soup.find_all("a", href=True):
        if a.get_text(" ", strip=True) == "View Standalone":
            return True
    return False


def parse_page(html):
    soup = BeautifulSoup(html, "html.parser")
    data = {"name": soup.find("h1").get_text(" ", strip=True) if soup.find("h1") else None}
    for key in SECTIONS:
        section = soup.find("section", id=SECTIONS[key])
        table = section.find("table") if section is not None else None
        data[key] = parse_table(table) if table is not None else {"columns": [], "rows": {}}
    data["documents"] = parse_documents(soup)
    data["top_ratios"] = parse_top_ratios(soup)
    data["growth"] = parse_growth_tables(soup)
    data["consolidated_available"] = has_consolidated(soup)
    return data


def get_company(ticker, statement=None, use_cache=True):
    """Tables + documents for a ticker. statement=None -> consolidated, else standalone
    if there is no consolidated. statement="standalone" forces the standalone page
    (banks report headline numbers standalone). None if screener doesn't know the ticker."""
    ticker = ticker.upper().strip()
    if statement is None:
        statement = "consolidated"
    try:
        html = fetch_html(ticker, statement, use_cache)
    except NotFound:
        return None
    data = parse_page(html)
    if statement == "consolidated" and not data["consolidated_available"]:
        statement = "standalone"
        data = parse_page(fetch_html(ticker, "standalone", use_cache))
    data["ticker"] = ticker
    data["statement"] = statement
    data["url"] = page_url(ticker, statement)
    data["fetched_on"] = date.today().isoformat()
    return data


def latest_quarter(company):
    """('Sep 2026', {'Sales': 73188.0, ...}) for the newest quarter column."""
    q = company["quarters"]
    if len(q["columns"]) == 0:
        return None, {}
    last = len(q["columns"]) - 1
    values = {}
    for name in q["rows"]:
        if len(q["rows"][name]) > last:
            values[name] = q["rows"][name][last]
    return q["columns"][last], values


# ---------- CLI ----------

def print_company(company):
    print("\n==========", company["ticker"], "|", company["name"], "|", company["statement"],
          "| consolidated exists:", company["consolidated_available"], "==========")
    for key in SECTIONS:
        table = company[key]
        print(key, "->", len(table["columns"]), "columns, rows:", list(table["rows"].keys()))
    quarter, values = latest_quarter(company)
    print("latest quarter", quarter, "->", {k: values[k] for k in list(values)[:6]})
    print("top ratios:", company["top_ratios"])
    print("growth:", company["growth"])
    docs = company["documents"]
    print("annual reports:", len(docs["annual_reports"]), "e.g.", docs["annual_reports"][:2])
    print("concalls:", len(docs["concalls"]), "e.g.", docs["concalls"][:2])


if __name__ == "__main__":
    for symbol in sys.argv[1:] or ["TCS"]:
        started = time.time()
        company = get_company(symbol)
        if company is None:
            print("\n", symbol, "-> not found on screener")
            continue
        print_company(company)
        print("took", round(time.time() - started, 1), "s")
