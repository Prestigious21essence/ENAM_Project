"""Digest for a time window: events (high -> medium -> collapsed low) + price/volume alerts.

Alerts are linked to the company's filings from the same day or up to 3 days
before (a filing after market close moves the stock the next trading day).
A medium event whose stock then moved past the price threshold is promoted to
high: the market is telling us it mattered.

Usage:
    python push\\digest.py            -> last 24 hours
    python push\\digest.py 72         -> last 72 hours
    python push\\digest.py 45d        -> last 45 days
"""
import json
import os
import sys
from collections import Counter
from datetime import datetime, timedelta

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from db import get_conn
from ingest.prices import alerts_for_range

PORTFOLIO_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "portfolio.json")
LINK_DAYS_BEFORE = 3

HIGH = 3
MEDIUM = 2
LOW = 1


def load_portfolio():
    with open(PORTFOLIO_PATH) as f:
        return json.load(f)


def load_events(from_text, to_text):
    """Events that overlap the window, each with its member filings."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, symbol, type, start, end, priority, headline, reason, member_ids, card_type, card "
        "FROM events WHERE start <= ? AND end >= ?", (to_text, from_text)).fetchall()

    events = []
    for row in rows:
        event = {"id": row[0], "symbol": row[1], "type": row[2], "start": row[3], "end": row[4],
                 "priority": row[5], "headline": row[6], "reason": row[7],
                 "card_type": row[9], "card": None, "filings": [], "alerts": []}
        if row[10]:
            event["card"] = json.loads(row[10])
        for member_id in json.loads(row[8]):
            f = conn.execute("SELECT datetime, subject, pdf_url FROM announcements WHERE id = ?",
                             (member_id,)).fetchone()
            event["filings"].append({"id": member_id, "datetime": f[0], "subject": f[1], "pdf_url": f[2]})
        events.append(event)
    conn.close()
    return events


def describe_alert(alert):
    parts = []
    if alert["price_alert"]:
        sign = "+" if alert["pct_change"] >= 0 else ""
        parts.append(sign + str(alert["pct_change"]) + "%")
    else:
        sign = "+" if alert["pct_change"] >= 0 else ""
        parts.append("price " + sign + str(alert["pct_change"]) + "%")
    if alert["volume_alert"]:
        parts.append("on " + str(alert["volume_ratio"]) + "x volume")
    return " ".join(parts)


def link_alerts(alerts, events):
    """Attach to each alert the events that had a filing in the days just before it."""
    for alert in alerts:
        alert["linked"] = []
        alert_day = datetime.strptime(alert["date"], "%Y-%m-%d")
        for event in events:
            if event["symbol"] != alert["symbol"]:
                continue
            for filing in event["filings"]:
                filing_day = datetime.strptime(filing["datetime"][:10], "%Y-%m-%d")
                days_before = (alert_day - filing_day).days
                if 0 <= days_before <= LINK_DAYS_BEFORE:
                    if days_before == 0:
                        when = "same day"
                    elif days_before == 1:
                        when = "1 day before"
                    else:
                        when = str(days_before) + " days before"
                    alert["linked"].append({"event_id": event["id"], "type": event["type"],
                                            "when": when, "days_before": days_before,
                                            "priority": event["priority"], "event": event})
                    event["alerts"].append(alert)
                    break

    promote_on_price_moves(alerts)


def promote_on_price_moves(alerts):
    """A medium event becomes high if the stock then moved past the price threshold,
    but only if it is the one plausible cause: filed the same day or the day before,
    and no high-priority event of the same company is linked to the same move."""
    for alert in alerts:
        if not alert["price_alert"]:
            continue
        has_high_cause = False
        for link in alert["linked"]:
            if link["priority"] == HIGH:
                has_high_cause = True
        if has_high_cause:
            continue
        candidates = []
        for link in alert["linked"]:
            if link["priority"] == MEDIUM and link["days_before"] <= 1:
                candidates.append(link)
        if len(candidates) == 1:
            event = candidates[0]["event"]
            event["priority"] = HIGH
            event["reason"] = "promoted: stock moved " + describe_alert(alert) + " right after this filing"


def data_as_of():
    """Latest filing time and latest price day in the database, plus `as_of`:
    the moment the data ends. The deployed database is a snapshot refreshed on a
    laptop, so windows like "last 24 hours" must end here, not at the clock time,
    or a snapshot opened days later would look empty."""
    conn = get_conn()
    filings = conn.execute("SELECT MAX(datetime) FROM announcements").fetchone()[0]
    prices = conn.execute("SELECT MAX(date) FROM prices").fetchone()[0]
    conn.close()

    candidates = []
    if filings:
        candidates.append(filings[:16])
    if prices:
        candidates.append(prices[:10] + " 23:59")   # EOD price: known by end of that day
    if candidates:
        as_of = max(candidates)
    else:
        as_of = datetime.now().strftime("%Y-%m-%d %H:%M")
    return {"filings": filings, "prices": prices, "as_of": as_of}


def latest_data_time():
    return datetime.strptime(data_as_of()["as_of"], "%Y-%m-%d %H:%M")


def get_digest(hours=24, start=None, end=None):
    """Digest for [start, end] (datetimes); default: the `hours` hours up to the
    latest data in the database (see data_as_of)."""
    data = load_portfolio()
    settings = data["settings"]
    now = latest_data_time()
    if end is not None:
        now = end
    if start is None:
        start = now - timedelta(hours=hours)
    from_text = start.strftime("%Y-%m-%d %H:%M")
    to_text = now.strftime("%Y-%m-%d %H:%M")

    # Load events from a few days earlier too: an alert in the window can be caused by
    # a filing made just before the window starts (e.g. results filed 2 days ago).
    link_from = (start - timedelta(days=LINK_DAYS_BEFORE)).strftime("%Y-%m-%d %H:%M")
    linkable_events = load_events(link_from, to_text)
    events = []
    for event in linkable_events:
        if event["end"] >= from_text:
            events.append(event)

    # Price data is end-of-day, so a 24 h window still looks at the last trading days
    alert_from = (start - timedelta(days=LINK_DAYS_BEFORE)).strftime("%Y-%m-%d")
    alert_to = now.strftime("%Y-%m-%d")
    alerts = []
    for company in data["portfolio"]:
        alerts.extend(alerts_for_range(company["symbol"], alert_from, alert_to,
                                       settings["price_move_pct"], settings["volume_multiple"],
                                       settings["volume_window_days"]))
    link_alerts(alerts, linkable_events)

    # The user decides which kinds of news can reach the top (Settings screen)
    for event in events:
        if event["priority"] == HIGH and event["type"] not in settings["alert_categories"]:
            event["priority"] = MEDIUM
            event["reason"] = "you turned off top alerts for " + event["type"]

    high = []
    medium = []
    low = []
    for event in sorted(events, key=lambda e: e["end"], reverse=True):
        if event["priority"] == HIGH:
            high.append(event)
        elif event["priority"] == MEDIUM:
            medium.append(event)
        else:
            low.append(event)

    low_counts = Counter()
    for event in low:
        low_counts[event["type"]] += 1

    alerts = sorted(alerts, key=lambda a: a["date"], reverse=True)
    return {"from": from_text, "to": to_text, "high": high, "medium": medium,
            "low_counts": dict(low_counts), "low": low, "alerts": alerts}


def print_event(event):
    print("  " + event["end"][:10], event["symbol"].ljust(10), event["type"].ljust(17), "|", event["headline"][:160])
    if event["reason"]:
        print("      why:", event["reason"])
    biggest = biggest_move(event["alerts"])
    if biggest is not None:
        print("      market:", describe_alert(biggest), "on", biggest["date"])


def biggest_move(alerts):
    biggest = None
    for alert in alerts:
        if biggest is None or abs(alert["pct_change"]) > abs(biggest["pct_change"]):
            biggest = alert
    return biggest


def print_digest(digest):
    print("\n=================== FINN digest:", digest["from"], "->", digest["to"], "===================")
    print("\nHIGH (" + str(len(digest["high"])) + ")")
    for event in digest["high"]:
        print_event(event)
    print("\nMEDIUM (" + str(len(digest["medium"])) + ")")
    for event in digest["medium"]:
        print_event(event)
    low_total = len(digest["low"])
    print("\nROUTINE, collapsed (" + str(low_total) + "):",
          ", ".join(str(n) + " " + t for t, n in sorted(digest["low_counts"].items(), key=lambda x: -x[1])))

    print("\nPRICE / VOLUME ALERTS (" + str(len(digest["alerts"])) + ")")
    for alert in digest["alerts"]:
        text = "  " + alert["date"] + " " + alert["symbol"].ljust(10) + " " + describe_alert(alert)
        if len(alert["linked"]) > 0:
            links = []
            for link in alert["linked"]:
                links.append(link["type"] + " filed " + link["when"])
            text = text + "  <- " + "; ".join(links)
        else:
            text = text + "  (no filing in the 3 days before)"
        print(text)


if __name__ == "__main__":
    hours = 24
    if len(sys.argv) == 2:
        arg = sys.argv[1]
        if arg.endswith("d"):
            hours = int(arg[:-1]) * 24
        else:
            hours = int(arg)
    print_digest(get_digest(hours))
