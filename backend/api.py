"""FINN API (FastAPI). Thin layer over the same functions refresh.py uses.

Run locally:   uvicorn api:app --reload      (from the backend folder)

Endpoints:
  GET  /health
  GET  /digest?hours=24            or  /digest?from=2026-11-01&to=2026-11-10
  GET  /alerts?days=30
  GET  /settings
  POST /settings                   body: any of the settings fields
  GET  /event/{event_id}
"""
import json
import os
from datetime import datetime, timedelta

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from db import get_conn
from ingest.prices import alerts_for_range
from push.digest import biggest_move, data_as_of, describe_alert, get_digest
from push.events import build_events

PORTFOLIO_PATH = os.path.join(os.path.dirname(__file__), "data", "portfolio.json")

# Settings the phone may change, with the allowed range for each number
NUMBER_SETTINGS = {
    "price_move_pct": (0.5, 20.0),
    "volume_multiple": (1.0, 10.0),
    "volume_window_days": (5, 60),
    "results_move_pct": (5.0, 100.0),
}
ALL_CATEGORIES = ["results", "M&A", "management_change", "fund_raise", "litigation", "pledging",
                  "credit_rating", "dividend", "capex", "press_release", "insider_trading"]

app = FastAPI(title="FINN API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # demo: the Vercel frontend and localhost
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ---------- helpers ----------

def load_portfolio():
    with open(PORTFOLIO_PATH) as f:
        return json.load(f)


def company_names():
    data = load_portfolio()
    names = {}
    for company in data["portfolio"] + data["research"]:
        names[company["symbol"]] = company["name"]
    return names


def parse_date(text, end_of_day=False):
    try:
        if len(text) == 10:
            day = datetime.strptime(text, "%Y-%m-%d")
            if end_of_day:
                day = day + timedelta(hours=23, minutes=59)
            return day
        return datetime.fromisoformat(text)
    except ValueError:
        raise HTTPException(status_code=400, detail="dates must look like 2026-11-10 or 2026-11-10T09:30")


def clean_alert(alert):
    """Alert without the back-references to events (those can't become JSON).
    Only meaningful links are kept (routine paperwork can't explain a price move),
    most important first; routine ones are just counted."""
    links = sorted(alert.get("linked", []), key=lambda link: -link.get("priority", 1))
    linked = []
    routine_links = 0
    for link in links:
        if link.get("priority", 1) <= 1:
            routine_links = routine_links + 1
            continue
        linked.append({"event_id": link["event_id"], "type": link["type"], "when": link["when"]})
    return {"symbol": alert["symbol"], "date": alert["date"], "pct_change": alert["pct_change"],
            "volume_ratio": alert["volume_ratio"], "price_alert": alert["price_alert"],
            "volume_alert": alert["volume_alert"], "text": describe_alert(alert),
            "linked": linked, "routine_links": routine_links}


def clean_event(event, names):
    biggest = biggest_move(event["alerts"])
    market = None
    if biggest is not None:
        market = clean_alert(biggest)
    return {"id": event["id"], "symbol": event["symbol"], "name": names.get(event["symbol"], event["symbol"]),
            "type": event["type"], "start": event["start"], "end": event["end"],
            "priority": event["priority"], "headline": event["headline"], "reason": event["reason"],
            "card_type": event["card_type"], "card": event["card"],
            "filings": event["filings"], "market": market}


# ---------- endpoints ----------

@app.get("/health")
def health():
    return {"ok": True, "data_as_of": data_as_of()}


@app.get("/health/sources")
def health_sources():
    """Can THIS server reach NSE, BSE and screener.in? (exchanges may block cloud IPs.)
    Makes one small request to each, for TCS (filings over the last 14 days).
    This one deliberately uses the real clock: it tests live reachability today,
    not the snapshot (the digest windows end at data_as_of instead)."""
    from ingest.announcements import fetch_bse, fetch_nse, make_nse_session
    import time

    to_date = datetime.now().date()
    from_date = to_date - timedelta(days=14)
    result = {}

    started = time.time()
    try:
        session = make_nse_session()
        items = fetch_nse(session, "TCS", from_date, to_date)
        result["nse"] = {"ok": True, "filings": len(items)}
    except Exception as e:
        result["nse"] = {"ok": False, "error": repr(e)[:200]}
    result["nse"]["seconds"] = round(time.time() - started, 1)

    started = time.time()
    try:
        items, name = fetch_bse("532540", "TCS", from_date, to_date)
        result["bse"] = {"ok": True, "filings": len(items)}
    except Exception as e:
        result["bse"] = {"ok": False, "error": repr(e)[:200]}
    result["bse"]["seconds"] = round(time.time() - started, 1)

    # screener.in (pull side): a live fetch, not the daily cache
    from ingest.screener import get_company, latest_quarter
    started = time.time()
    try:
        company = get_company("TCS", use_cache=False)
        quarter, values = latest_quarter(company)
        result["screener"] = {"ok": True, "latest_quarter": quarter, "sales": values.get("Sales")}
    except Exception as e:
        result["screener"] = {"ok": False, "error": repr(e)[:200]}
    result["screener"]["seconds"] = round(time.time() - started, 1)
    return result


@app.get("/digest")
def digest(hours: int = 24, from_: str = Query(None, alias="from"), to: str = None):
    # "from" is a Python keyword, hence the alias
    return build_digest_response(hours, from_, to)


def build_digest_response(hours, start_text, end_text):
    start = None
    end = None
    if start_text:
        start = parse_date(start_text)
    if end_text:
        end = parse_date(end_text, end_of_day=True)
    result = get_digest(hours=hours, start=start, end=end)
    names = company_names()

    high = []
    for e in result["high"]:
        high.append(clean_event(e, names))
    medium = []
    for e in result["medium"]:
        medium.append(clean_event(e, names))
    low = []
    for e in result["low"]:
        low.append({"id": e["id"], "symbol": e["symbol"], "name": names.get(e["symbol"], e["symbol"]),
                    "type": e["type"], "end": e["end"], "headline": e["headline"]})
    alerts = []
    for a in result["alerts"]:
        alerts.append(clean_alert(a))

    return {"from": result["from"], "to": result["to"], "data_as_of": data_as_of(),
            "high": high, "medium": medium, "low": low, "low_counts": result["low_counts"],
            "alerts": alerts}


@app.get("/alerts")
def alerts(days: int = 30):
    result = get_digest(hours=days * 24)
    names = company_names()
    items = []
    for a in result["alerts"]:
        item = clean_alert(a)
        item["name"] = names.get(a["symbol"], a["symbol"])
        items.append(item)
    return {"days": days, "data_as_of": data_as_of(), "alerts": items}


@app.get("/settings")
def get_settings():
    data = load_portfolio()
    return {"settings": data["settings"], "all_categories": ALL_CATEGORIES,
            "portfolio": data["portfolio"], "research": data["research"]}


@app.post("/settings")
def update_settings(changes: dict = Body(...)):
    data = load_portfolio()
    settings = data["settings"]

    for key in changes:
        value = changes[key]
        if key in NUMBER_SETTINGS:
            low, high = NUMBER_SETTINGS[key]
            try:
                number = float(value)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail=key + " must be a number")
            if number < low or number > high:
                raise HTTPException(status_code=400, detail=key + " must be between " + str(low) + " and " + str(high))
            if key == "volume_window_days":
                number = int(number)
            settings[key] = number
        elif key == "alert_categories":
            if not isinstance(value, list):
                raise HTTPException(status_code=400, detail="alert_categories must be a list")
            chosen = []
            for category in value:
                if category in ALL_CATEGORIES:
                    chosen.append(category)
            settings[key] = chosen
        else:
            raise HTTPException(status_code=400, detail="unknown setting: " + key)

    with open(PORTFOLIO_PATH, "w") as f:
        json.dump(data, f, indent=2)

    # Thresholds change which events are high, so re-judge them (no LLM calls, < 1 s)
    build_events()
    return {"settings": settings}


@app.get("/event/{event_id}")
def get_event(event_id: str):
    conn = get_conn()
    row = conn.execute(
        "SELECT id, symbol, type, start, end, priority, headline, reason, member_ids, card_type, card "
        "FROM events WHERE id = ?", (event_id,)).fetchone()
    if row is None:
        conn.close()
        raise HTTPException(status_code=404, detail="event not found")

    filings = []
    for member_id in json.loads(row[8]):
        f = conn.execute("SELECT id, datetime, subject, details, summary, category, pdf_url "
                         "FROM announcements WHERE id = ?", (member_id,)).fetchone()
        filings.append({"id": f[0], "datetime": f[1], "subject": f[2], "details": f[3],
                        "summary": f[4], "category": f[5], "pdf_url": f[6]})
    conn.close()
    filings = sorted(filings, key=lambda f: f["datetime"])

    # Price moves from the event's first filing until 3 days after its last one
    settings = load_portfolio()["settings"]
    start_day = row[3][:10]
    end_day = (datetime.strptime(row[4][:10], "%Y-%m-%d") + timedelta(days=3)).strftime("%Y-%m-%d")
    moves = []
    for a in alerts_for_range(row[1], start_day, end_day, settings["price_move_pct"],
                              settings["volume_multiple"], settings["volume_window_days"]):
        moves.append(clean_alert(a))

    card = None
    if row[10]:
        card = json.loads(row[10])
    return {"id": row[0], "symbol": row[1], "name": company_names().get(row[1], row[1]),
            "type": row[2], "start": row[3], "end": row[4], "priority": row[5],
            "headline": row[6], "reason": row[7], "card_type": row[9], "card": card,
            "filings": filings, "market_moves": moves}
