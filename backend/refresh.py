"""Daily job, end to end:
  1. prices        (Yahoo EOD -> SQLite)
  2. announcements (NSE, BSE fallback)
  3. classify      (rules, then cheap LLM)
  4. results cards for new results filings
  5. management cards for new management-change filings
  6. one-line summaries for vague filings
  7. group into events + event-level priority
  8. print the digest

Every step catches its own errors, so one failure (e.g. Gemini busy) doesn't stop
the rest; the failed work is retried on the next refresh. Cards and LLM answers
are cached, so a second refresh on the same day costs (almost) no tokens.

Usage:
    python refresh.py                 -> full refresh, digest for the last 24 h
    python refresh.py --no-fetch 45d  -> skip downloads, digest for the last 45 days
"""
import json
import os
import sys
import time

sys.path.append(os.path.dirname(__file__))
from db import get_conn
from ingest.announcements import fetch_all
from ingest.prices import download_prices
from push import mgmt_change, results_extract
from push.classify import classify_all
from push.digest import get_digest, print_digest
from push.events import build_events
from push.summarize import summarize_vague_filings

PORTFOLIO_PATH = os.path.join(os.path.dirname(__file__), "data", "portfolio.json")


def step(name, function):
    print("\n----- " + name + " -----")
    started = time.time()
    try:
        result = function()
        print("  done in", round(time.time() - started, 1), "s")
        return result
    except Exception as e:
        print("  FAILED:", repr(e)[:200], "(continuing)")
        return None


def update_prices():
    with open(PORTFOLIO_PATH) as f:
        symbols = []
        for c in json.load(f)["portfolio"]:
            symbols.append(c["symbol"])
    download_prices(symbols)


def update_announcements():
    items, from_date, to_date = fetch_all()
    print("  fetched", len(items), "filings from", from_date, "to", to_date)


def update_classification():
    results = classify_all()
    print("  classified", len(results), "filings")


def build_results_cards():
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, symbol, pdf_url FROM announcements WHERE category = 'results' "
        "AND subject = 'Outcome of Board Meeting' "
        "AND id NOT IN (SELECT announcement_id FROM results_cards)").fetchall()
    conn.close()
    print("  new results filings to read:", len(rows))
    for announcement_id, symbol, pdf_url in rows:
        try:
            card = results_extract.build_card(symbol, announcement_id, pdf_url)
        except Exception as e:
            print("  ", symbol, "card failed (will retry next refresh):", repr(e)[:100])
            continue
        card["announcement_id"] = announcement_id
        results_extract.save_card(card)      # also saves "no P&L page" so we don't retry it daily
        if "error" in card:
            print("  ", symbol, "->", card["error"])
        else:
            print("  ", symbol, "->", results_extract_line(card))


def results_extract_line(card):
    parts = []
    for row in card["rows"]:
        parts.append(row["metric"] + " " + str(row["yoy_pct"]) + "% YoY")
    return ", ".join(parts)


def build_mgmt_cards():
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, symbol FROM announcements WHERE category = 'management_change' "
        "AND id NOT IN (SELECT announcement_id FROM mgmt_cards)").fetchall()
    conn.close()
    print("  new management filings to read:", len(rows))
    for announcement_id, symbol in rows:
        try:
            card = mgmt_change.build_card(announcement_id)
        except Exception as e:
            print("  ", symbol, "card failed (will retry next refresh):", repr(e)[:100])
            continue
        mgmt_change.save_card(card)
        for change in card["changes"]:
            print("  ", symbol, "->", change["headline"][:110], "[" + change["seniority"] + "]")


def update_summaries():
    print("  summarised", summarize_vague_filings(), "filings")


def update_events():
    events, n_filings = build_events()
    high = 0
    for e in events:
        if e["priority"] == 3:
            high = high + 1
    print(" ", n_filings, "filings ->", len(events), "events,", high, "high")


if __name__ == "__main__":
    fetch = "--no-fetch" not in sys.argv
    hours = 24
    for arg in sys.argv[1:]:
        if arg.endswith("d") and arg[:-1].isdigit():
            hours = int(arg[:-1]) * 24
        elif arg.isdigit():
            hours = int(arg)

    started = time.time()
    if fetch:
        step("1. prices", update_prices)
        step("2. announcements", update_announcements)
    step("3. classify", update_classification)
    step("4. results cards", build_results_cards)
    step("5. management cards", build_mgmt_cards)
    step("6. summaries", update_summaries)
    step("7. events", update_events)
    digest = step("8. digest", lambda: get_digest(hours))
    if digest is not None:
        print_digest(digest)
    print("\nRefresh finished in", round(time.time() - started), "s")
