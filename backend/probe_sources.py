"""One raw request to NSE and one to BSE for TCS (last 14 days).

Prints status, item count and the raw JSON of the first item, so the fetcher's
field names can be matched to what actually comes back.
"""
import json
from datetime import date, timedelta

import requests

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

to_date = date.today()
from_date = to_date - timedelta(days=14)

# ---------- NSE ----------
print("========== NSE ==========")
try:
    session = requests.Session()
    session.headers.update(BROWSER_HEADERS)
    r1 = session.get("https://www.nseindia.com", timeout=10)
    print("homepage status:", r1.status_code, "| cookies:", list(session.cookies.keys()))
    session.headers["Referer"] = "https://www.nseindia.com/companies-listing/corporate-filings-announcements"

    params = {
        "index": "equities",
        "symbol": "TCS",
        "from_date": from_date.strftime("%d-%m-%Y"),
        "to_date": to_date.strftime("%d-%m-%Y"),
    }
    r = session.get("https://www.nseindia.com/api/corporate-announcements", params=params, timeout=15)
    print("api status:", r.status_code, "| content-type:", r.headers.get("content-type"))
    data = r.json()
    print("type:", type(data).__name__, "| items:", len(data))
    if len(data) > 0:
        print(json.dumps(data[0], indent=2))
except Exception as e:
    print("NSE FAILED:", repr(e)[:300])

# ---------- BSE ----------
print("\n========== BSE ==========")
try:
    params = {
        "pageno": 1,
        "strCat": "-1",
        "strPrevDate": from_date.strftime("%Y%m%d"),
        "strScrip": "532540",
        "strSearch": "P",
        "strToDate": to_date.strftime("%Y%m%d"),
        "strType": "C",
        "subcategory": "-1",
    }
    headers = dict(BROWSER_HEADERS)
    headers["Referer"] = "https://www.bseindia.com/"
    headers["Origin"] = "https://www.bseindia.com"
    r = requests.get("https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w",
                     params=params, headers=headers, timeout=15)
    print("api status:", r.status_code, "| content-type:", r.headers.get("content-type"))
    data = r.json()
    print("top-level keys:", list(data.keys()))
    table = data.get("Table", [])
    print("items in Table:", len(table))
    if len(table) > 0:
        print(json.dumps(table[0], indent=2))
    if data.get("Table1"):
        print("Table1:", data["Table1"])
except Exception as e:
    print("BSE FAILED:", repr(e)[:300])
