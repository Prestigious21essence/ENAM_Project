# FINN — Full Build Roadmap

**Deadline:** Sun 15 Nov 2026 · **Started:** Tue 10 Nov 2026 (≈5 working days left)
**Submit to:** assessment@enam.com · Subject: **"IIT Delhi – AI Engineer - 2027"**

**Rule for this file:** tick boxes as you finish. Every step has a **"Done when"** check — don't move on until it passes.

---

## Overview — the whole micro path

| # | Step | Day | Status |
|---|------|-----|--------|
| 1 | Setup machine, repo, keys | Tue 10 | ☑ (GitHub push deferred until prototype works) |
| 2 | Choose portfolio + research companies (`portfolio.json`) | Tue 10 | ☑ |
| 3 | Prices: download EOD data + price/volume alert logic | Tue 10 | ☑ |
| 4 | Announcements: fetch filings (NSE, BSE fallback) | Tue 10 / Wed 11 | ☑ (NSE works) |
| 5 | Classify filings (rules first, cheap LLM for unclear ones) + priority | Wed 11 | ☑ (done Tue 10) |
| 6 | Results card: Revenue / EBITDA / PBT / PAT, QoQ + YoY | Wed 11 | ☑ (done Tue 10; tested TCS, ITC, SBIN) |
| 7 | Management-change card: bio of incoming person | Wed 11 | ☑ (done Wed 11, 00:00) |
| 8 | Digest builder (time window) + alert feed + `refresh.py` | Wed 11 | ☑ (done Wed 11; 24 high events in 45 days) |
| 9 | Screener scraper: financial tables + AR / concall links (any ticker) | Thu 12 | ☐ |
| 10 | Document pipeline: download → text → chunks → cache | Thu 12 | ☐ |
| 11 | Numeric research sections (no LLM): snapshot, trajectory, balance sheet, cash quality | Thu 12 | ☐ |
| 12 | Guidance extraction + promised-vs-delivered | Thu 12 | ☐ |
| 13 | Business snapshot + bull/bear with citations | Thu 12 | ☐ |
| 14 | FastAPI endpoints | Fri 13 | ◐ push side done Wed 11 (`/digest`, `/alerts`, `/settings`, `/event`, `/health/sources`); `/research`, `/ask` to come |
| 15 | Mobile frontend: Today, Alerts, Settings, Research, Ask | Fri 13 | ◐ Today (morning brief), Alerts, Settings, event detail done Wed 11; Research, Ask to come |
| 16 | Deploy (backend Render, frontend Vercel) + test on phone | Sat 14 | ☐ prepared (`render.yaml`, README); on hold until GitHub push is approved |
| 17 | Robustness: unseen tickers, missing data, caching, cost log | Sat 14 | ☐ |
| 18 | Optional: Telegram push | Sat 14 | ☐ |
| 19 | Writeup, AI history export, final phone check, submit | Sun 15 | ☐ |

**If behind schedule:** cut steps 13, 18 and the "Ask" screen first. Never cut testing (17).

---

## STEP 1 — Setup machine, repo, keys  *(~1 hr)*

### 1.1 Install tools (Windows)
- [x] **Python 3.11+** from python.org → during install **tick "Add python.exe to PATH"** *(3.13.13 already installed)*
- [x] **Node.js 20 LTS** from nodejs.org *(v26.13.0 already installed)*
- [x] **Git** from git-scm.com *(2.56.0 already installed)*
- [ ] **VS Code** + extensions: Python, ESLint, Tailwind CSS IntelliSense

Check in a new terminal (PowerShell):
```
python --version     # 3.11 or higher
node --version       # v20.x
git --version
```

### 1.2 Create the project folder
⚠ **Code lives in the `finn` subfolder of the ENAM AI folder** (inside OneDrive, so the reviewer chat can read it). **Pause OneDrive syncing while working** (OneDrive icon → ⚙ → Pause syncing → 24 hours, repeat daily); otherwise `node_modules`, `.venv` and `finn.db` cause slow syncs, `EPERM` errors and locked-database errors.

```
mkdir "C:\Users\Lenovo\OneDrive\Documents\ENAM AI\finn"
cd "C:\Users\Lenovo\OneDrive\Documents\ENAM AI\finn"
mkdir backend, backend\ingest, backend\push, backend\pull, backend\data, frontend, ai-history
```

Final layout we're aiming for:
```
finn/
├── backend/
│   ├── ingest/        prices.py, announcements.py, screener.py
│   ├── push/          classify.py, results_extract.py, mgmt_change.py, digest.py
│   ├── pull/          docs.py, guidance.py, report.py
│   ├── data/          portfolio.json, finn.db (sqlite), cache/ (pdfs, text)
│   ├── db.py          database helper
│   ├── llm.py         model router + response cache
│   ├── refresh.py     daily job
│   ├── api.py         FastAPI app
│   └── requirements.txt
├── frontend/          React app
├── ai-history/        exported AI chats (submission item!)
├── README.md
└── WRITEUP.md
```

### 1.3 Python virtual environment
```
cd "C:\Users\Lenovo\OneDrive\Documents\ENAM AI\finn\backend"
python -m venv .venv
.venv\Scripts\activate          # prompt now shows (.venv)
```
If PowerShell blocks activation: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, then retry.

Create `backend/requirements.txt`:
```
yfinance
pandas
requests
beautifulsoup4
pymupdf
pdfplumber
fastapi
uvicorn
python-dotenv
google-genai
```
Install:
```
pip install -r requirements.txt
```

### 1.4 API keys
- [x] **Gemini:** go to aistudio.google.com → "Get API key" → create key (free tier). This is the cheap/bulk model.
- [ ] (Optional now) **Groq** key at console.groq.com — backup cheap model.
- [ ] Stronger model for reasoning (Gemini Pro or Claude) — can decide on Day 3.

Create `backend/.env` (never commit this):
```
GEMINI_API_KEY=paste_your_key_here
```

Create `finn/.gitignore`:
```
.venv/
__pycache__/
.env
backend/data/finn.db
backend/data/cache/
node_modules/
dist/
```

### 1.5 Test the LLM works
`backend/llm_test.py`:
```python
import os
from dotenv import load_dotenv
from google import genai

load_dotenv()
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# Use the current "Flash" model name shown in AI Studio
response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents="Reply with exactly: FINN is alive",
)
print(response.text)
```
```
python llm_test.py
```
⚠ **Tested 2026-11-10:** `gemini-2.5-flash` returns 404 for new keys, and `gemini-3.8-flash` / `3.7-flash` often return 503 (high demand). The real `llm_test.py` tries `3.8-flash → 3.5-flash → 3.5-flash-lite` with SDK retries off; `gemini-3.5-flash` answered. `llm.py` (Step 5) needs the same fallback list.

### 1.6 GitHub
*(Deferred: local git repo + per-step commits exist in `finn/`; create the GitHub repo and push only once the prototype works.)*
- [ ] Create a new repo `finn` on github.com (public is fine — they need to see it)
```
cd "C:\Users\Lenovo\OneDrive\Documents\ENAM AI\finn"
git init
git add .
git commit -m "Project skeleton"
git branch -M main
git remote add origin https://github.com/<your-username>/finn.git
git push -u origin main
```

### 1.7 AI history habit
- [ ] Every AI chat you use (Claude, ChatGPT, Cursor) → save the share link / export into `ai-history/links.md` as you go. This chat counts.

**✅ Done when:** `python llm_test.py` prints "FINN is alive", and the repo is visible on GitHub.

---

## STEP 2 — Choose portfolio + research companies  *(~30 min)*

### 2.1 Why these picks
- Mix of **sectors** (IT, banks, energy, consumer, pharma, auto, industrials) and **sizes** (large caps + a few mid/small caps) → more varied filings for the demo.
- **Timing advantage:** Q2 FY27 results season (Oct–mid Nov) has just happened, so almost every company has a fresh **results filing** and **concall** → great for the results card and promised-vs-delivered.
- Research companies are deliberately **outside** the portfolio and include stories where "promised vs delivered" is interesting.

### 2.2 Create `backend/data/portfolio.json`
`bse` = BSE scrip code (needed for the BSE fallback in Step 4).
⚠ **Verify each BSE code** by searching the company on bseindia.com — fix any that don't match.

```json
{
  "portfolio": [
    {"symbol": "TCS",        "bse": "532540", "name": "Tata Consultancy Services", "sector": "IT"},
    {"symbol": "PERSISTENT", "bse": "533179", "name": "Persistent Systems",        "sector": "IT"},
    {"symbol": "AFFLE",      "bse": "542752", "name": "Affle India",               "sector": "Ad-tech"},
    {"symbol": "HDFCBANK",   "bse": "500180", "name": "HDFC Bank",                 "sector": "Bank"},
    {"symbol": "SBIN",       "bse": "500112", "name": "State Bank of India",       "sector": "Bank"},
    {"symbol": "BAJFINANCE", "bse": "500034", "name": "Bajaj Finance",             "sector": "NBFC"},
    {"symbol": "RELIANCE",   "bse": "500325", "name": "Reliance Industries",       "sector": "Conglomerate"},
    {"symbol": "TATAPOWER",  "bse": "500400", "name": "Tata Power",                "sector": "Power"},
    {"symbol": "ITC",        "bse": "500875", "name": "ITC",                       "sector": "FMCG"},
    {"symbol": "TITAN",      "bse": "500114", "name": "Titan Company",             "sector": "Consumer"},
    {"symbol": "SUNPHARMA",  "bse": "524715", "name": "Sun Pharma",                "sector": "Pharma"},
    {"symbol": "APOLLOHOSP", "bse": "508869", "name": "Apollo Hospitals",          "sector": "Healthcare"},
    {"symbol": "MARUTI",     "bse": "532500", "name": "Maruti Suzuki",             "sector": "Auto"},
    {"symbol": "LT",         "bse": "500510", "name": "Larsen & Toubro",           "sector": "Infra"},
    {"symbol": "HAL",        "bse": "541154", "name": "Hindustan Aeronautics",     "sector": "Defence"},
    {"symbol": "DIXON",      "bse": "540699", "name": "Dixon Technologies",        "sector": "Electronics mfg"},
    {"symbol": "POLYCAB",    "bse": "542652", "name": "Polycab India",             "sector": "Cables"},
    {"symbol": "DEEPAKNTR",  "bse": "506401", "name": "Deepak Nitrite",            "sector": "Chemicals"}
  ],
  "research": [
    {"symbol": "ASIANPAINT", "bse": "500820", "name": "Asian Paints"},
    {"symbol": "PIDILITIND", "bse": "500331", "name": "Pidilite Industries"},
    {"symbol": "IRCTC",      "bse": "542830", "name": "IRCTC"},
    {"symbol": "COALINDIA",  "bse": "533278", "name": "Coal India"}
  ],
  "settings": {
    "price_move_pct": 4.0,
    "volume_multiple": 2.0,
    "volume_window_days": 20,
    "alert_categories": ["results", "M&A", "management_change", "fund_raise", "litigation", "pledging", "credit_rating"]
  }
}
```
Feel free to swap companies — just keep the sector/size mix.

**✅ Done when:** `portfolio.json` exists, has 15–20 portfolio + 3–5 research entries, and BSE codes are checked.

---

## STEP 3 — Prices: EOD data + price/volume alert logic  *(~1.5 hr)*

### 3.1 What we're building
- Download ~6 months of daily data (open, high, low, close, volume) for every portfolio stock from Yahoo (`SYMBOL.NS`).
- Store it in SQLite so we never re-download what we already have.
- A function that checks the **latest day** against the user's thresholds:
  - **Price alert:** |today's % change| ≥ `price_move_pct`
  - **Volume alert:** today's volume ≥ `volume_multiple` × average of previous `volume_window_days` days

Dry-run example: DIXON closes at 15,600 today vs 16,500 yesterday → change = (15600 − 16500) / 16500 × 100 = **−5.45%** → beyond ±4% → **price alert**. Its volume today is 2.1M, the 20-day average is 0.8M → 2.1 / 0.8 = **2.6×** → beyond 2× → **volume alert**.

### 3.2 `backend/db.py` — one place that creates the tables
```python
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "finn.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS prices (
            symbol TEXT, date TEXT,
            open REAL, high REAL, low REAL, close REAL, volume INTEGER,
            PRIMARY KEY (symbol, date)
        )""")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS announcements (
            id TEXT PRIMARY KEY,
            symbol TEXT, source TEXT, datetime TEXT,
            subject TEXT, details TEXT, pdf_url TEXT,
            category TEXT, priority INTEGER, summary TEXT
        )""")
    return conn
```

### 3.3 `backend/ingest/prices.py`
```python
import json
import os
import sys
import yfinance as yf

sys.path.append(os.path.dirname(os.path.dirname(__file__)))   # so we can import db.py
from db import get_conn

PORTFOLIO_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "portfolio.json")


def load_portfolio():
    with open(PORTFOLIO_PATH) as f:
        return json.load(f)


def download_prices(symbols, period="6mo"):
    conn = get_conn()
    for symbol in symbols:
        df = yf.Ticker(symbol + ".NS").history(period=period)
        if df.empty:
            print("No data for", symbol)
            continue
        for date, row in df.iterrows():
            conn.execute(
                "INSERT OR REPLACE INTO prices VALUES (?, ?, ?, ?, ?, ?, ?)",
                (symbol, date.strftime("%Y-%m-%d"),
                 float(row["Open"]), float(row["High"]), float(row["Low"]),
                 float(row["Close"]), int(row["Volume"])),
            )
        conn.commit()
        print(symbol, "->", len(df), "days")
    conn.close()


def check_alerts(symbol, price_move_pct=4.0, volume_multiple=2.0, window=20):
    conn = get_conn()
    rows = conn.execute(
        "SELECT date, close, volume FROM prices WHERE symbol = ? ORDER BY date DESC LIMIT ?",
        (symbol, window + 1),
    ).fetchall()
    conn.close()

    if len(rows) < window + 1:
        return []

    today_date, today_close, today_volume = rows[0]
    yesterday_close = rows[1][1]

    pct_change = (today_close - yesterday_close) / yesterday_close * 100
    previous_volumes = [r[2] for r in rows[1:]]
    avg_volume = sum(previous_volumes) / len(previous_volumes)
    volume_ratio = today_volume / avg_volume if avg_volume > 0 else 0

    alerts = []
    if abs(pct_change) >= price_move_pct:
        alerts.append({"symbol": symbol, "date": today_date, "type": "price",
                       "value": round(pct_change, 2)})
    if volume_ratio >= volume_multiple:
        alerts.append({"symbol": symbol, "date": today_date, "type": "volume",
                       "value": round(volume_ratio, 2)})
    return alerts


if __name__ == "__main__":
    data = load_portfolio()
    settings = data["settings"]
    symbols = [c["symbol"] for c in data["portfolio"]]

    download_prices(symbols)

    print("\n--- Alerts ---")
    for s in symbols:
        for a in check_alerts(s, settings["price_move_pct"],
                              settings["volume_multiple"], settings["volume_window_days"]):
            print(a)
```

### 3.4 Run and test
```
cd "C:\Users\Lenovo\OneDrive\Documents\ENAM AI\finn\backend"
python ingest\prices.py
```
- [x] Every symbol prints ~120+ days. Any "No data" → the NSE symbol is wrong; fix it in `portfolio.json`. *(18/18, 126 days each)*
- [x] **Force-test the alerts:** temporarily set `price_move_pct` to `0.5` and `volume_multiple` to `1.0` → you should now see several alerts. Put the real values back afterwards. *(now a CLI override: `python ingest\prices.py 0.5 1.0` → 17 alerts; real thresholds → 1)*
- [x] Sanity-check one stock: compare the last close in your DB with the price on Google/NSE. *(TCS: DB 2475.40 NSE vs BSE 2471.10)*

**✅ Done when:** all 18 stocks are in `finn.db`, and the alert check prints alerts when thresholds are lowered.

---

## STEP 4 — Announcements: fetch filings (NSE first, BSE fallback)  *(~2–3 hr — riskiest step)*

### 4.1 What we're building
For any symbol and date range, fetch every corporate announcement and store it in one common format:
```
id, symbol, source (NSE/BSE), datetime, subject, details, pdf_url
```
`category`, `priority` and `summary` stay empty for now — filled in Step 5.

### 4.2 Why two sources
- **NSE** has a JSON API, but it **blocks plain scripts**: you must first visit the homepage with browser-like headers to get cookies, then call the API with the same session. It sometimes still fails (and often blocks cloud servers).
- **BSE** has a separate API that is usually more lenient but needs the numeric **BSE code** (that's why it's in `portfolio.json`).
- The code tries NSE; if that fails for a symbol, it falls back to BSE.

### 4.3 `backend/ingest/announcements.py`
```python
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
    # Visiting these pages first gives us the cookies NSE expects
    session.get("https://www.nseindia.com", timeout=10)
    session.get("https://www.nseindia.com/companies-listing/corporate-filings-announcements", timeout=10)
    session.headers["Referer"] = "https://www.nseindia.com/companies-listing/corporate-filings-announcements"
    return session


def parse_nse_time(text):
    # NSE format looks like "10-Nov-2026 14:30:12"
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
            "subject": a.get("desc"),               # e.g. "Outcome of Board Meeting"
            "details": a.get("attchmntText"),       # one-paragraph description
            "pdf_url": a.get("attchmntFile"),
        })
    return items


# ---------- BSE ----------
def parse_bse_time(text):
    # BSE format looks like "2026-11-10T14:30:12.883"
    try:
        return datetime.fromisoformat(text[:19]).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return text


def fetch_bse(bse_code, symbol, from_date, to_date):
    url = "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
    params = {
        "pageno": 1,
        "strCat": "-1",
        "strPrevDate": from_date.strftime("%Y%m%d"),
        "strScrip": bse_code,
        "strSearch": "P",
        "strToDate": to_date.strftime("%Y%m%d"),
        "strType": "C",
        "subcategory": "-1",
    }
    headers = dict(BROWSER_HEADERS)
    headers["Referer"] = "https://www.bseindia.com/"
    headers["Origin"] = "https://www.bseindia.com"

    response = requests.get(url, params=params, headers=headers, timeout=15)
    response.raise_for_status()

    items = []
    for a in response.json().get("Table", []):
        pdf_url = None
        if a.get("ATTACHMENTNAME"):
            pdf_url = "https://www.bseindia.com/xml-data/corpfiling/AttachLive/" + a["ATTACHMENTNAME"]
        items.append({
            "id": "BSE-" + str(a.get("NEWSID")),
            "symbol": symbol,
            "source": "BSE",
            "datetime": parse_bse_time(a.get("NEWS_DT")),
            "subject": (a.get("CATEGORYNAME") or "") + " | " + (a.get("NEWSSUB") or ""),
            "details": a.get("HEADLINE"),
            "pdf_url": pdf_url,
        })
    return items


# ---------- Combined ----------
def fetch_announcements(company, from_date, to_date, nse_session=None):
    symbol = company["symbol"]
    if nse_session is not None:
        try:
            return fetch_nse(nse_session, symbol, from_date, to_date)
        except Exception as e:
            print("  NSE failed for", symbol, "->", e, "| trying BSE")
    return fetch_bse(company["bse"], symbol, from_date, to_date)


def save_announcements(items):
    conn = get_conn()
    for it in items:
        conn.execute(
            "INSERT OR IGNORE INTO announcements (id, symbol, source, datetime, subject, details, pdf_url) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (it["id"], it["symbol"], it["source"], it["datetime"],
             it["subject"], it["details"], it["pdf_url"]),
        )
    conn.commit()
    conn.close()


if __name__ == "__main__":
    with open(PORTFOLIO_PATH) as f:
        portfolio = json.load(f)["portfolio"]

    to_date = date.today()
    from_date = to_date - timedelta(days=14)

    try:
        session = make_nse_session()
    except Exception as e:
        print("Could not open NSE session:", e)
        session = None

    all_items = []
    for company in portfolio:
        try:
            items = fetch_announcements(company, from_date, to_date, session)
        except Exception as e:
            print("  BOTH failed for", company["symbol"], "->", e)
            items = []
        print(company["symbol"], "->", len(items), "announcements")
        all_items.extend(items)
        time.sleep(1)          # be polite, avoid getting blocked

    save_announcements(all_items)

    print("\nTotal:", len(all_items))
    print("\nMost common subjects (use these to write classification rules in Step 5):")
    for subject, count in Counter(it["subject"] for it in all_items).most_common(40):
        print(f"{count:4d}  {subject}")
```

### 4.4 Run and test
```
python ingest\announcements.py
```
- [x] Each symbol prints a count (results season → most should be > 0). *(all 18 > 0; 134 via NSE, 140 via BSE)*
- [x] Note **which source worked** (NSE or BSE). If NSE fails everywhere, that's fine — BSE is the plan. *(Both work from the laptop; NSE used, no fallback needed)*
- [x] Open 2–3 `pdf_url`s in your browser to confirm they're real filing PDFs. *(5 checked: 3 NSE + 2 BSE, all real PDFs)*
- [x] **Save the "Most common subjects" output** to `backend/data/subjects_sample.txt` — Step 5's rules are written from this list. *(+ `subjects_sample_bse.txt`)*

⚠ **Corrections to the draft code above (the real file is `finn/backend/ingest/announcements.py`):** BSE subject uses `SUBCATNAME` (CATEGORYNAME is only "Company Update"); BSE pages via `Table1[0].ROWCNT`; BSE needs the full browser headers (a short User-Agent gets an empty body); NSE homepage visit alone is enough for cookies; NSE `voiceSummary` is saved as `summary` when present (only 10/134).

### 4.5 If it breaks
| Problem | Fix |
|---|---|
| NSE returns 401/403 | Normal. Fallback to BSE handles it. Optionally retry `make_nse_session()` once. |
| BSE returns empty `Table` | Check the BSE code; try a wider date range; check field names by printing `response.json()` once. |
| Field names differ from code | Print one raw item (`print(response.json()[0])`) and adjust the keys. |
| Works on laptop, fails on server later | Expected for NSE. Plan: run `refresh.py` locally or rely on BSE in production. |

**✅ Done when:** `finn.db` has announcements for most portfolio stocks, PDF links open, and `subjects_sample.txt` is saved. **Commit + push.**

---

## STEP 5 onwards — summary (detailed versions to be added as we reach them)

**5. Classify + prioritise** — `push/classify.py`: keyword rules on `subject`/`details` mapped to the 17 reference categories (e.g. "financial results" → results, "resignation"/"appointment" → management_change, "ESOP"/"trading window"/"compliance certificate" → unclassified). Only items no rule matches go to the cheap LLM (batched, cached). Priority table: results/M&A/mgmt change/pledging/litigation/fund_raise = high; dividend/credit_rating/capex/press_release = medium; the rest = low/collapsed. Log how many items needed the LLM (cost story for writeup).

*(Done — `push/classify.py`. Built as above, plus: litigation-like filings always go to the LLM with the PDF text to check whether the company itself is the party; the LLM also flags "minor" items (procedural, tiny amounts, intra-group), which drop to medium; debt issues (NCD/CP) count as medium. 349 filings → 105 high / 77 medium / 167 low; 56 via LLM in 6 batched calls.)*

**6. Results card** — download results PDF → PyMuPDF text → cheap LLM returns JSON `{period, revenue, ebitda, pbt, pat}` for current Q, previous Q, same Q last year (consolidated). If EBITDA missing: PBT + finance costs + depreciation − other income. Compute QoQ/YoY % in Python. Cross-check revenue/PAT against screener's quarterly table; flag "unverified" if off.
*(Done — `push/results_extract.py`. Changes from the plan: the P&L page is sent as an **image**, not text, because some filings (SBI) are scans with garbled OCR. EBITDA also subtracts exceptional items and share of associates; revenue is net of excise duty. Banks show NII / pre-provision operating profit / PBT / PAT (standalone). The screener cross-check is still to do (Step 9).)*

**7. Management-change card** — extract name, role, joining/leaving, and the "brief profile" section from the filing PDF (appointment filings include it). Optional web search for extra background. One-line card: "New CFO: X — ex-Y (Z yrs), CA".

*(Done — `push/mgmt_change.py`. Bio comes from the filing only; if missing ("details already provided"), it is taken from the company's earlier management filing that names the person. Seniority (top/board/other) is rule-based from the role. Web search for extra background not done.)*

**8. Digest + alerts + refresh** — `push/digest.py`: given a time window, return items grouped high → medium → collapsed low, with summaries. `refresh.py`: prices → announcements → classify → enrich → alerts. Link alerts to same-day filings ("−7% on 3× volume · results filed yesterday").
*(Done — plus `push/events.py` (filings → events, event-level priority) and `push/summarize.py` (one-liners for vague filings). Alerts link to filings 0–3 days before; a medium event is promoted only if it is the sole plausible cause of a price move. 349 filings → 140 events → 24 high.)*

**9. Screener scraper** — for any ticker: P&L, balance sheet, cash-flow, quarterly tables + annual report and concall transcript links.

**10. Document pipeline** — download latest AR + last 4 transcripts → text per page → chunks with (doc, page) labels → cache to disk so each company is processed once.

**11. Numeric sections (no LLM)** — financial snapshot, multi-year trajectory, debt/D-E/working capital, CFO vs PAT cash conversion, FCF — straight from screener tables.

**12. Guidance + promised vs delivered** — cheap LLM extracts promises per transcript as JSON (metric, target, period, quote, page) → Python matches against actuals → strong LLM writes the verdict per promise (met / missed / pending) with citations.

**13. Business snapshot + bull/bear** — retrieval over chunks, answer only from provided text, "not disclosed" if absent, every claim cited.

**14. FastAPI** — `/digest?from&to`, `/alerts`, `/settings` (GET/POST), `/research/{ticker}`, `/ask`.

**15. Frontend** — React + Tailwind PWA. Screens: Today (digest), Alerts, Settings (thresholds, categories), Research (any ticker, tappable citations), Ask.

**16. Deploy** — backend Render/Railway, frontend Vercel; test on real phone.

**17. Robustness** — test 3–4 unseen tickers (bank, small-cap, recent IPO); graceful "not available" states; cache everything; token/cost log.

**18. Optional Telegram push** — bot sends high-priority items + alerts after each refresh.

**19. Submit** — WRITEUP.md (built / decisions & trade-offs / left out / next), export AI history, final phone check, email.

---

## Remaining work — micro tasks (planned Fri 13 Nov, 18:00 · reviewer chat)

**Time left:** Fri evening, Sat, Sun morning. Do them in order. **D** tasks are done by hand / by Antigravity and run in parallel with the **M** tasks. **F** tasks are the finish.
Each prompt from the reviewer covers **one** task ID. Claude Code: do only that task, then commit, tick it here, and log it.

### Rules for the whole pull side (M2–M10)
- **Primary sources only:** screener financial tables, concall transcripts, annual reports, results filings. **Not** screener's own "About", "Pros/Cons" or AI notes (those are secondary). No news, no model outside knowledge: every prompt says "answer only from the text below; say 'not disclosed' if it isn't there".
- **Every figure and claim carries a citation:** `{doc, page}` or `{screener table, column}`.
- **Maths in Python**, never in the LLM.
- **Cheap model** for extraction; **stronger model** only for the verdict step (M6).
- **Any NSE ticker** must work. Missing data → a clear "not available" state, never a crash.

| ID | Task | Who | When | Status |
|---|---|---|---|---|
| D1 | Push `092bd53` to GitHub | Antigravity | Fri | ☑ |
| M1 | LLM resilience + rebuild 5 results cards | Claude Code | Fri | ☑ (a, c done; b coded, live test needs `FALLBACK_API_KEY` in `.env`) |
| D2 | Render backend deploy | Shubhankur | Fri | ☑ https://finn-api-iqfg.onrender.com |
| D3 | Vercel frontend deploy + phone test | Shubhankur | Fri | ☑ https://enam-project.vercel.app |
| M2 | Screener scraper (any ticker) + results-card cross-check | Claude Code | Fri/Sat | ☑ (18/18 cards match screener) |
| M3 | Numeric research sections (no LLM) | Claude Code | Sat | ☑ (TCS, HDFCBANK, ASIANPAINT, SHAILY; file is `pull/financials.py`, see M4 log) |
| M4 | Transcript pipeline (last 4 concalls → pages → cache) | Claude Code | Sat | ☑ (TCS, ASIANPAINT, SHAILY: 4/4 verified quarters) |
| M5 | Guidance extraction with verified quotes | Claude Code | Sat | ☑ (TCS 14, ASIANPAINT 18 promises; 32/32 quotes verified in Python) |
| M6 | Promised vs delivered (verdicts + scorecard) | Claude Code | Sat | ☑ (TCS 7 threads, ASIANPAINT 8; verdicts on lite tonight, re-run on 3.6-flash after the quota reset) |
| M7 | `/research/{ticker}` API (background build, progressive) | Claude Code | Sat | ☑ (numbers in ~1 s, stages progressive, quota-safe; 5 tickers pre-built in finn.db) |
| M8 | Research tab in the app | Claude Code | Sat | ☑ (search + chips, scorecard hero, citation sheet, numbers cards, sources, building/quota states) |
| D4 | Push + redeploy + phone test of Research | Antigravity + Shubhankur | Sat night | ☑ `0f4e212` live; TCS research + unseen BRITANNIA built live on Render (reviewer, 375 px); real-phone check by Shubhankur still to do |
| M9 | Robustness on unseen tickers + cost summary | Claude Code | Sun | ☑ (5 unseen tickers incl. a bank, a small-cap, a recent IPO and a no-calls company; 2 bugs fixed; cost table in the log) |
| M10 | Business snapshot + bull/bear (cited) | Claude Code | Sun, after D4 | ☑ (5th stage "story"; every bullet cited and verified; 6 tickers pre-built) |
| M9b | Correctness fixes from the reviewer's audit (management-card rules + verb check; research recency, actual filters, Python-final verdicts, segment threads, call dates, growth columns) | Claude Code | Sun evening | ☑ (all 11 tickers rebuilt; audit: 0 verdict differences, no transcript older than 15 months) |
| F1 | AI history export into `ai-history/` | Claude Code + Shubhankur | Sun | ☑ (4 sessions as markdown; no share links by decision, `OTHER_AI_TOOLS.md` instead) |
| F2 | `WRITEUP.md` + email text | Claude Code + reviewer | Sun | ☑ (`WRITEUP_FINAL.md` → `finn/WRITEUP.md`, pushed in `8467b3a`, tag `submission`) |
| R1 | Refresh push data to today + check it (results vs screener, management rules, summary check, screenshots) | Claude Code | Sun night | ☑ (30 new filings to 13 Nov; 2 results cards, 4 management cards; 27/30 summaries verified; 149 events / 25 high; local commit, not pushed) |
| R2 | Auto-refresh drift fix: classify new filings only, restore audited DB, 3 targeted reclassifications | Claude Code | Sun night | ☑ (152 events / 25 high / 55 medium; no-cache refresh = 0 LLM calls, events identical; local commit) |
| F3 | Final checks + send email | Shubhankur | Sun | ☐ (push done; repo public, phone check, email left) |

**Cut order if late:** M10 → M9 down to 1 ticker → M8 citations as plain links. **Never cut D4:** a demo that doesn't run is the worst outcome.

### Done-when checks
- **D1:** `git log origin/main -1` shows `092bd53`; `git ls-files` lists no `.env`, `cache/`, `node_modules/`, `dist/` or `cost_log` file.
- **M1:** (a) a daily-quota 429 marks that model "out" for the rest of the run (no more retries on it); (b) one second free provider is the last fallback for text calls (its free tier must take a ~25k-token prompt; key in `.env` only; image calls stay on Gemini); (c) the 3 flagged cards (Reliance, Sun Pharma, Titan) and 2 missing ones (Affle, L&T) rebuilt with the full model. **Done when:** a forced-fallback test (Gemini switched off by an env flag) answers; 17/17 cards exist, with the count passing all 4 checks reported; Titan = 20,614 / 2,984 / 3,000 / 2,393; DB committed.
- **D2 (Render):** dashboard → New → Blueprint → pick the repo → it reads `render.yaml` → set `GEMINI_API_KEY` (and the M1 second key) → Apply. Open `/health`, `/digest?hours=24`, `/health/sources`. **Done when:** the URL and the NSE/BSE result are in the log.
- **D3 (Vercel):** Add New → Project → the repo → Root Directory `frontend` → env `VITE_API_URL=<Render URL, no trailing slash>` → Deploy. (Vite bakes the env at build time: if you add it later, redeploy.) **Done when:** it opens on a real phone; Today, Alerts and event detail work; the waking banner shows on a cold start.
- **M2:** `ingest/screener.py` takes any ticker → quarterly, P&L, balance sheet, cash flow, ratios tables + document links (annual reports; concall transcripts/PPTs by quarter). Consolidated first, standalone fallback. Raw HTML cached (one fetch per ticker per day). Screener added to `/health/sources`. Cross-check every results card's revenue and PAT against the screener quarterly table (flag > 2% off). **Done when:** works for TCS, HDFCBANK, ASIANPAINT and one unseen small-cap; a bad ticker gives a clean "not found"; the cross-check table for all cards is in the log.
- **M3:** `pull/numbers.py`, no LLM. Financial snapshot (latest FY + TTM: revenue, OPM, PAT, ROE, ROCE); Trajectory (3/5-yr sales and profit CAGR, margin direction); Balance sheet (borrowings, D/E, debtor/inventory/payable days, cash conversion cycle); Cash quality (CFO/PAT by year and cumulative; FCF: screener's cash-flow table already has `Free Cash Flow` and `CFO/EBITDA` rows, and the P&L has a `TTM` column). Every number carries `{table, column}`. A bank variant. One plain-English takeaway per section from **rules**, not the LLM. **Done when:** printed for TCS, HDFCBANK, ASIANPAINT; 2 numbers hand-checked against the screener page.
- **M4:** `pull/docs.py`: last 4 concall transcripts from M2's links → download → text per page → cache (each document processed once, ever). Scanned PDF → flagged. A missing quarter → recorded as missing. **Screener's concall labels are not reliable** (TCS: two "Jul 2026" entries, one of them linking to the *Jul 2025* Q1 FY26 transcript; "Mar 2026" has only a PPT): read the real quarter and call date from the transcript's first page, dedupe by that, and take the 4 most recent distinct quarters. **Done when:** TCS and ASIANPAINT have 4 cached transcripts with page counts; a company with fewer is handled; timings logged.
- **M5:** `pull/guidance.py`: cheap model, one call per transcript → JSON list `{metric, target (number / range / direction), period, verbatim quote, page, speaker}`. Only explicit forward guidance on headline items (growth, margins, capex, volumes, debt), not vague hopes. **Python checks that each quote really appears on that page** (whitespace-normalised); unverified ones are dropped and counted. **Done when:** promise lists for TCS and ASIANPAINT, the verified-quote rate reported, tokens logged.
- **M6 refinements (reviewer, Sat 23:40):**
  1. **Group repeated promises into threads** (same metric across calls: TCS 26–28% margin band, Asian Paints 18–20% margin / 8–10% volume). Track how the target **moved**: reiterated / raised / lowered / dropped (no longer mentioned). A quiet walk-back (e.g. TCS "towards 26%" → "exit FY27 at 25%+") is the most valuable finding.
  2. **Use the company's own definition for actuals.** TCS's "operating margin" is EBIT; screener's OPM is EBITDA-based, so comparing them would wrongly say "met". Volume growth, TCV and gross margin aren't on screener at all. Actuals for company-defined metrics come from the **later transcripts** (the cheap model extracts the reported figure, and the quote is verified in Python like M5). Screener is used only where definitions match (revenue growth, PAT).
  3. **Python decides whether the period is over** (FY26 done, H2 FY27 not yet, "medium term" never "missed"). Verdicts: met / missed / partly / on track / behind / pending / can't tell. "Can't tell" is fine for loose items (e.g. "demand to improve").
  4. **Stronger model only for the verdict** (check live what the free tier offers, log it); every verdict cites the promise quote **and** the evidence (doc + page, or screener table + column).
- **M6:** `pull/promises.py`: for each promise, evidence = screener numbers (Python computes the actual) and/or the later transcripts' pages. Stronger model writes the verdict (met / missed / partly / pending / can't tell) + one sentence, citing **both** the promise and the evidence. Roll-up: a scorecard + one "credibility" line. **Done when:** scorecards for 2 companies; 2 verdicts hand-checked against the PDFs; cost per company logged.
- **M7:** `/research/{ticker}` starts a background build and returns status + whichever sections are ready (numbers in seconds, promises later). The result is cached in the DB per ticker. Pre-build the 4 research companies and commit the DB. **Done when:** curl on an unseen ticker shows the status moving to done; the second call takes < 1 s; a bad ticker → 404 with a message.
- **M8:** Research tab: ticker search (any NSE symbol); the promised-vs-delivered scorecard as the hero; numeric sections as compact cards; every citation tappable (bottom sheet: the quote + "Open PDF, p. N"); progress states while building. **Done when:** 375 px screenshots of a research company, and of an unseen ticker while loading and when done.
- **D4:** push, Render/Vercel redeploy automatically; on the phone, open Research for one pre-built company **and** one unseen ticker live.
- **M9:** 3 unseen tickers (a bank, a small-cap, a recent IPO with < 4 transcripts); every "not available" state seen; a cost summary from `cost_log.csv` (tokens per research run, cache-hit rate, model mix). **Done when:** a results table is in the log.
- **M10:** business snapshot + bull/bear, every claim cited to transcript/AR pages (verified like M5), answer only from the provided text. **Done after D4**, so a working deployed app is already safe; then a second push.
- **F1:** Claude Code sessions (`%USERPROFILE%\.claude\projects\…\*.jsonl`) exported as readable markdown into `finn/ai-history/`; share links to the reviewer chats and Antigravity chats in `ai-history/links.md`.
- **F2:** `WRITEUP.md` + the email body: what was built / key decisions and trade-offs / what was left out / what's next.
- **F3:** repo public (or reviewers added); `.env` not on GitHub; every tab checked on the phone; email sent to assessment@enam.com, subject "IIT Delhi – AI Engineer - 2027".
