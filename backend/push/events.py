"""Group filings into events and decide each event's priority.

One event = filings of the same company and the same kind, each filed within
GAP_DAYS of the previous one. "results" and "earnings_call" are one kind, so a
results event = filing + deck + press release + shareholder letter + transcript.

Deals, court cases and fund raises are stories that run for weeks (agreement ->
completion, NCLT -> NCLAT), so for those the gap is LONG_GAP_DAYS.

Event priority starts as the highest priority of its filings, then a few
event-level judgments bring the headline list down to what really matters:
  - results:     high only if PAT moved >= results_move_pct YoY (from the card)
                 or the stock moved >= price_move_pct within 3 days of the results
  - management:  high only if a top person (CEO/MD/CFO/Chairman) joins or leaves
                 (re-appointments and divisional heads don't count)
  - M&A:         new / merged wholly owned subsidiary, timeline extension -> medium
  - fund raise:  conversion of already-approved warrants -> medium

Usage:  python push\\events.py
"""
import json
import os
import sys
from collections import Counter
from datetime import datetime, timedelta

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from db import get_conn
from ingest.prices import alerts_for_range
from push.mgmt_change import seniority

PORTFOLIO_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "portfolio.json")
GAP_DAYS = 10
LONG_GAP_DAYS = 35
LONG_STORY_TYPES = ["M&A", "litigation", "fund_raise", "management_change"]
MARKET_REACTION_DAYS = 3

HIGH = 3
MEDIUM = 2
LOW = 1

MINOR_MNA_WORDS = ["incorporat", "extension of timeline", "revised the estimated completion",
                   "amalgamation of its wholly owned subsidiary", "nil consideration"]
MINOR_FUND_RAISE_WORDS = ["conversion of warrants", "exercise request"]


def event_kind(category):
    if category in ["results", "earnings_call"]:
        return "results"
    return category or "unclassified"


def load_settings():
    with open(PORTFOLIO_PATH) as f:
        return json.load(f)["settings"]


def group_filings(rows):
    """rows: dicts with id, symbol, category, datetime, ... -> list of events (dicts)."""
    rows = sorted(rows, key=lambda r: (r["symbol"], event_kind(r["category"]), r["datetime"]))
    events = []
    for row in rows:
        when = datetime.strptime(row["datetime"], "%Y-%m-%d %H:%M")
        kind = event_kind(row["category"])
        last = None
        if len(events) > 0:
            last = events[-1]
        gap = GAP_DAYS
        if kind in LONG_STORY_TYPES:
            gap = LONG_GAP_DAYS
        if (last is not None and last["symbol"] == row["symbol"] and last["type"] == kind
                and (when - last["end_time"]).days <= gap):
            last["members"].append(row)
            last["end_time"] = when
        else:
            events.append({"symbol": row["symbol"], "type": kind, "members": [row],
                           "start_time": when, "end_time": when})
    return events


def all_text(event):
    parts = []
    for m in event["members"]:
        parts.append((m["details"] or "") + " " + (m["summary"] or ""))
    return " ".join(parts).lower()


def has_any(text, words):
    for word in words:
        if word in text:
            return True
    return False


def find_card(conn, table, member_ids):
    """Return the first card (dict) stored for any of these filings, else None."""
    for member_id in member_ids:
        row = conn.execute("SELECT card FROM " + table + " WHERE announcement_id = ?",
                           (member_id,)).fetchone()
        if row is not None:
            card = json.loads(row[0])
            if "rows" in card or "changes" in card:
                return card
    return None


def all_mgmt_changes(conn, member_ids):
    """All people changes in the event's cards, each person+change only once
    (Tata Power filed 3 letters that each list the same 3 directors)."""
    changes = []
    seen = []
    for member_id in member_ids:
        row = conn.execute("SELECT card FROM mgmt_cards WHERE announcement_id = ?",
                           (member_id,)).fetchone()
        if row is None:
            continue
        for change in json.loads(row[0]).get("changes", []):
            name = change.get("name") or "?"
            key = name.lower().split()[-1] + "|" + str(change.get("change"))
            if key in seen:
                continue
            seen.append(key)
            # recompute with the current rule, so old cards follow rule fixes
            change["seniority"] = seniority(change.get("role"))
            changes.append(change)
    return changes


def market_reaction(symbol, filed_at, settings):
    """Biggest price alert in the few trading days after a filing, or None."""
    start = filed_at[:10]
    end = (datetime.strptime(start, "%Y-%m-%d") + timedelta(days=MARKET_REACTION_DAYS)).strftime("%Y-%m-%d")
    biggest = None
    for alert in alerts_for_range(symbol, start, end, settings["price_move_pct"],
                                  settings["volume_multiple"], settings["volume_window_days"]):
        if alert["price_alert"]:
            if biggest is None or abs(alert["pct_change"]) > abs(biggest["pct_change"]):
                biggest = alert
    return biggest


def results_filed_at(event):
    """Date of the main results filing (the board outcome), else the first filing."""
    for m in event["members"]:
        if m["category"] == "results" and m["subject"] == "Outcome of Board Meeting":
            return m["datetime"]
    return event["members"][0]["datetime"]


def results_line(card):
    """'Revenue 73,188 cr (+11.2% YoY) · PAT 13,934 cr (+14.9% YoY)'"""
    parts = []
    for row in card["rows"]:
        if row["metric"] in ["Revenue", "Net interest income", "PAT"]:
            text = row["metric"] + " " + "{:,.0f}".format(row["value_cr"]) + " cr"
            if row["yoy_pct"] is not None:
                sign = "+" if row["yoy_pct"] >= 0 else ""
                text = text + " (" + sign + str(row["yoy_pct"]) + "% YoY)"
            parts.append(text)
    return " · ".join(parts)


def best_member(event):
    """The filing that best describes the event: highest priority, then most recent."""
    best = event["members"][0]
    for m in event["members"]:
        if m["priority"] > best["priority"]:
            best = m
        elif m["priority"] == best["priority"] and m["datetime"] > best["datetime"]:
            best = m
    return best


def judge_event(conn, event, settings):
    """Set priority, headline, reason and card for one event."""
    member_ids = []
    for m in event["members"]:
        member_ids.append(m["id"])
    priority = max(m["priority"] for m in event["members"])
    best = best_member(event)
    headline = best["summary"] or best["details"] or best["subject"]
    reason = ""
    card_type = None
    card = None
    text = all_text(event)

    if event["type"] == "results" and priority == HIGH:
        card = find_card(conn, "results_cards", member_ids)
        limit = settings["results_move_pct"]
        reaction = market_reaction(event["symbol"], results_filed_at(event), settings)
        if card is not None:
            card_type = "results"
            headline = "Q2 results: " + results_line(card)
            pat_yoy = None
            for row in card["rows"]:
                if row["metric"] == "PAT":
                    pat_yoy = row["yoy_pct"]
            if pat_yoy is not None and abs(pat_yoy) >= limit:
                reason = "PAT moved " + str(pat_yoy) + "% YoY (>= " + str(limit) + "%)"
            elif reaction is not None:
                reason = "stock moved " + str(reaction["pct_change"]) + "% on " + reaction["date"] + " after results"
            else:
                priority = MEDIUM
                reason = "results in line: PAT within " + str(limit) + "% YoY, no big price move"
        elif reaction is not None:
            reason = "stock moved " + str(reaction["pct_change"]) + "% after results (card unavailable)"
        else:
            priority = MEDIUM
            reason = "results card unavailable - open the filing"

    elif event["type"] == "management_change" and priority == HIGH:
        changes = all_mgmt_changes(conn, member_ids)
        if len(changes) > 0:
            card_type = "management"
            card = {"changes": changes}
            top_changes = []
            for change in changes:
                if change["seniority"] == "top" and change.get("change") in ["joining", "leaving", "role_change"]:
                    top_changes.append(change)
            if len(top_changes) > 0:
                headline = " | ".join(c["headline"] for c in top_changes[:2])
                reason = "top management change"
            else:
                priority = MEDIUM
                headline = " | ".join(c["headline"] for c in changes[:2])
                reason = "board / senior-management change or re-appointment, not a new CEO/MD/CFO/Chairman"

    elif event["type"] == "M&A" and priority == HIGH:
        if has_any(text, MINOR_MNA_WORDS) and len(event["members"]) <= 2:
            priority = MEDIUM
            reason = "new subsidiary / timeline update"

    elif event["type"] == "fund_raise" and priority == HIGH:
        if has_any(text, MINOR_FUND_RAISE_WORDS) and not has_any(text, ["qip", "qualified institution", "preferential issue"]):
            priority = MEDIUM
            reason = "conversion of warrants approved earlier"

    if len(event["members"]) > 1:
        headline = headline + " (" + str(len(event["members"])) + " filings)"

    event_id = event["symbol"] + "|" + event["type"] + "|" + event["start_time"].strftime("%Y-%m-%d %H:%M")
    return {
        "id": event_id, "symbol": event["symbol"], "type": event["type"],
        "start": event["start_time"].strftime("%Y-%m-%d %H:%M"),
        "end": event["end_time"].strftime("%Y-%m-%d %H:%M"),
        "priority": priority, "headline": headline, "reason": reason,
        "member_ids": member_ids, "card_type": card_type, "card": card,
    }


def build_events():
    settings = load_settings()
    conn = get_conn()
    cursor = conn.execute(
        "SELECT id, symbol, category, priority, datetime, subject, details, summary, pdf_url "
        "FROM announcements WHERE category IS NOT NULL")
    columns = [d[0] for d in cursor.description]
    rows = []
    for values in cursor.fetchall():
        rows.append(dict(zip(columns, values)))

    events = []
    for event in group_filings(rows):
        events.append(judge_event(conn, event, settings))

    conn.execute("DELETE FROM events")
    for e in events:
        card_text = None
        if e["card"] is not None:
            card_text = json.dumps(e["card"])
        conn.execute("INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     (e["id"], e["symbol"], e["type"], e["start"], e["end"], e["priority"],
                      e["headline"], e["reason"], json.dumps(e["member_ids"]), e["card_type"], card_text))
    conn.commit()
    conn.close()
    return events, len(rows)


if __name__ == "__main__":
    events, n_filings = build_events()
    counts = Counter(e["priority"] for e in events)
    print(n_filings, "filings ->", len(events), "events:", counts[HIGH], "high,",
          counts[MEDIUM], "medium,", counts[LOW], "low")
    print("\nHigh-priority events:")
    for e in sorted(events, key=lambda e: e["end"], reverse=True):
        if e["priority"] == HIGH:
            print("-", e["end"][:10], e["symbol"].ljust(10), e["type"].ljust(17), "|", e["headline"][:150])
