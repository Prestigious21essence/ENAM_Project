"""Check that every BSE code in portfolio.json points to the right company.

For each company we ask BSE for the scrip header and compare:
  - BSE's SecurityId (its ticker) with our NSE symbol
  - BSE's full company name with our name (by eye: printed side by side)
"""
import json
import os
import time

import requests

PORTFOLIO_PATH = os.path.join(os.path.dirname(__file__), "data", "portfolio.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.bseindia.com/",
    "Origin": "https://www.bseindia.com",
}


def get_bse_info(bse_code):
    url = "https://api.bseindia.com/BseIndiaAPI/api/ComHeadernew/w"
    params = {"quotetype": "EQ", "scripcode": bse_code, "seriesid": ""}
    header_data = requests.get(url, params=params, headers=HEADERS, timeout=15).json()

    url = "https://api.bseindia.com/BseIndiaAPI/api/getScripHeaderData/w"
    params = {"Debtflag": "", "scripcode": bse_code, "seriesid": ""}
    name_data = requests.get(url, params=params, headers=HEADERS, timeout=15).json()

    ticker = header_data.get("SecurityId") or ""
    full_name = ""
    if name_data.get("Cmpname"):
        full_name = name_data["Cmpname"].get("FullN") or ""
    return ticker, full_name


if __name__ == "__main__":
    with open(PORTFOLIO_PATH) as f:
        data = json.load(f)

    companies = data["portfolio"] + data["research"]
    problems = 0
    for company in companies:
        try:
            ticker, full_name = get_bse_info(company["bse"])
        except Exception as e:
            ticker, full_name = "", "ERROR: " + str(e)

        if ticker == company["symbol"]:
            status = "OK      "
        else:
            status = "MISMATCH"
            problems += 1
        print(status, company["bse"], company["symbol"].ljust(11), "| BSE says:",
              ticker.ljust(11), "|", full_name, "| ours:", company["name"])
        time.sleep(0.5)

    print("\nChecked", len(companies), "companies,", problems, "mismatches")
