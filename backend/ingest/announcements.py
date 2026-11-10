"""Fetch corporate announcements (NSE first, BSE fallback) into SQLite.

Usage:
    python ingest\\announcements.py          -> NSE first, BSE if NSE fails
    python ingest\\announcements.py bse      -> BSE only (also checks BSE company names)
    python ingest\\announcements.py nse      -> NSE only

Field names below were checked against real responses on 2026-11-10
(see probe_sources.py).
"""
import json
import os
import sys
import time
from collections import Counter
from datetime import date, datetime, timedelta

import requests

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from db import get_conn

PORTFOLIO_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "portfolio.json")
SUBJECTS_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "subjects_sample.txt")

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}


# ---------- NSE ----------
def make_nse_session():
    session = requests.Session()
    session.headers.update(BROWSER_HEADERS)
    # Visiting the homepage first gives us the cookies NSE expects
    session.get("https://www.nseindia.com", timeout=10)
    session.headers["Referer"] = "https://www.nseindia.com/companies-listing/corporate-filings-announcements"
    return session


def parse_nse_time(text):
    # NSE format: "09-Nov-2026 17:12:15"
    try:
        return datetime.strptime(text, "%d-%b-%Y %H:%M:%S").strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return text


def fetch_nse(session, symbol, from_date, to_date):
    url = "https://www.nseindia.com/api/corporate-announcements"
    params = {
        "index": "equities",
        "symbol": symbol,
        "from_date": from_date.strftime("%d-%m-%Y"),
        "to_date": to_date.strftime("%d-%m-%Y"),
    }
    response = session.get(url, params=params, timeout=15)
    response.raise_for_status()

    items = []
    for a in response.json():
        items.append({
            "id": "NSE-" + str(a.get("seq_id")),
            "symbol": symbol,
            "source": "NSE",
            "datetime": parse_nse_time(a.get("an_dt")),
            "subject": a.get("desc"),               # e.g. "Analysts/Institutional Investor Meet/Con. Call Updates"
            "details": a.get("attchmntText"),       # one-line description
            "pdf_url": a.get("attchmntFile"),
            "summary": a.get("voiceSummary"),       # NSE's own paragraph summary (free!)
        })
    return items


# ---------- BSE ----------
def parse_bse_time(text):
    # BSE format: "2026-11-09T16:59:25.653"
    try:
        return datetime.fromisoformat(text[:19]).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return text


def fetch_bse(bse_code, symbol, from_date, to_date):
    """Returns (items, company_name_from_bse)."""
    url = "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
    headers = dict(BROWSER_HEADERS)
    headers["Referer"] = "https://www.bseindia.com/"
    headers["Origin"] = "https://www.bseindia.com"

    items = []
    bse_name = None
    page = 1
    while page <= 20:                     # safety limit
        params = {
            "pageno": page,
            "strCat": "-1",
            "strPrevDate": from_date.strftime("%Y%m%d"),
            "strScrip": bse_code,
            "strSearch": "P",
            "strToDate": to_date.strftime("%Y%m%d"),
            "strType": "C",
            "subcategory": "-1",
        }
        response = requests.get(url, params=params, headers=headers, timeout=15)
        response.raise_for_status()
        data = response.json()

        rows = data.get("Table", [])
        if len(rows) == 0:
            break

        for a in rows:
            bse_name = a.get("SLONGNAME")
            pdf_url = None
            if a.get("ATTACHMENTNAME"):
                pdf_url = "https://www.bseindia.com/xml-data/corpfiling/AttachLive/" + a["ATTACHMENTNAME"]

            # SUBCATNAME ("Analyst / Investor Meet") is more useful than
            # CATEGORYNAME ("Company Update"), so prefer it.
            subject = a.get("SUBCATNAME") or a.get("CATEGORYNAME") or ""
            items.append({
                "id": "BSE-" + str(a.get("NEWSID")),
                "symbol": symbol,
                "source": "BSE",
                "datetime": parse_bse_time(a.get("NEWS_DT")),
                "subject": subject,
                "details": a.get("HEADLINE") or a.get("NEWSSUB"),
                "pdf_url": pdf_url,
                "summary": None,                  # BSE gives no summary; Step 5 fills it
            })

        total_rows = 0
        if data.get("Table1"):
            total_rows = data["Table1"][0].get("ROWCNT", 0)
        if len(items) >= total_rows:
            break
        page = page + 1

    return items, bse_name


# ---------- Combined ----------
def fetch_announcements(company, from_date, to_date, nse_session=None, only_source=None):
    symbol = company["symbol"]
    if only_source != "bse" and nse_session is not None:
        try:
            return fetch_nse(nse_session, symbol, from_date, to_date)
        except Exception as e:
            if only_source == "nse":
                raise
            print("  NSE failed for", symbol, "->", e, "| trying BSE")

    items, bse_name = fetch_bse(company["bse"], symbol, from_date, to_date)
    if bse_name:
        print("  BSE name for", company["bse"], "=", bse_name, "| ours:", company["name"])
    return items


def save_announcements(items):
    conn = get_conn()
    for it in items:
        conn.execute(
            "INSERT OR IGNORE INTO announcements "
            "(id, symbol, source, datetime, subject, details, pdf_url, summary) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (it["id"], it["symbol"], it["source"], it["datetime"],
             it["subject"], it["details"], it["pdf_url"], it["summary"]),
        )
    conn.commit()
    conn.close()


if __name__ == "__main__":
    only_source = None
    if len(sys.argv) == 2:
        only_source = sys.argv[1].lower()

    with open(PORTFOLIO_PATH) as f:
        portfolio = json.load(f)["portfolio"]

    to_date = date.today()
    from_date = to_date - timedelta(days=14)

    session = None
    if only_source != "bse":
        try:
            session = make_nse_session()
        except Exception as e:
            print("Could not open NSE session:", e)

    all_items = []
    for company in portfolio:
        try:
            items = fetch_announcements(company, from_date, to_date, session, only_source)
        except Exception as e:
            print("  FAILED for", company["symbol"], "->", e)
            items = []
        source = "-"
        if len(items) > 0:
            source = items[0]["source"]
        print(company["symbol"], "->", len(items), "announcements from", source)
        all_items.extend(items)
        time.sleep(1)          # be polite, avoid getting blocked

    save_announcements(all_items)

    counts = Counter()
    for it in all_items:
        counts[it["subject"]] += 1

    lines = []
    lines.append("Most common subjects, " + str(from_date) + " to " + str(to_date)
                 + " (" + str(len(all_items)) + " announcements)")
    for subject, count in counts.most_common(40):
        lines.append(str(count).rjust(4) + "  " + str(subject))

    print("\nTotal:", len(all_items))
    print("\n".join(lines))

    with open(SUBJECTS_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\nSaved to", SUBJECTS_PATH)
