"""Research for any NSE ticker, built in stages and kept in the DB.

Stages, in order (each one's result is saved as soon as it is ready):
  financials   screener tables -> 4 numeric sections (pull/financials.py)      seconds, no LLM
  transcripts  last 5 concall transcripts, text per page (pull/docs.py)        seconds, no LLM
  guidance     management's promises with verified quotes (pull/guidance.py)   ~5 cheap-model calls
  promises     promised vs delivered scorecard (pull/promises.py)              ~5 cheap + ~8 stronger calls
  story        business snapshot + bull vs bear, cited (pull/snapshot.py)      1 cheap + 1 stronger call

Table `research` (ticker, stage, status, json, updated_at). Status per stage:
  pending | running | done | waiting_quota | error | not_found

Quota-safe: when every LLM model is out for the day, the LLM stages end as "waiting_quota"
(not an error); the numbers and transcripts still show. A later build_research() call
resumes from the first stage that isn't done. Nothing here raises for a bad ticker or a
dead model: the caller gets statuses.

build_research(ticker)  -> runs the stages that still need running (one at a time per ticker)
get_research(ticker)    -> {"ticker", "status", "progress", "stages": {...}, "sections": {...}} from the DB
start_research(ticker)  -> financials now (sync, seconds), the rest in a background thread

Usage:  python pull\\research.py TCS ASIANPAINT        (build, print statuses)
"""
import json
import os
import re
import sqlite3
import sys
import threading
import time
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from db import get_conn
from ingest.screener import get_company
from pull.docs import get_transcripts
from pull.financials import build_numbers
from pull.guidance import extract_guidance
from pull.promises import build_scorecard
from pull.snapshot import build_story

STAGES = ["financials", "transcripts", "guidance", "promises", "story"]
LLM_STAGES = ["guidance", "promises", "story"]
RETRY_AFTER_MINUTES = 10        # don't re-attempt a waiting_quota / error stage on every poll
TICKER_PATTERN = re.compile(r"^[A-Z0-9&\-]{1,20}$")

_lock = threading.Lock()
_building = set()               # tickers with a build thread running right now


# ---------- DB ----------

def now_text():
    """ISO 8601 with the server's UTC offset, so the app can show it in the viewer's local time."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def save_stage(ticker, stage, status, data=None):
    """Write one stage row. Several build threads share the SQLite file, so a locked
    database is retried a few times rather than losing the write (a lost "done" left
    a stage frozen at "running" while the thread died: seen with 3 tickers at once)."""
    payload = json.dumps(data, ensure_ascii=False, default=str) if data is not None else None
    for attempt in range(5):
        try:
            conn = get_conn()
            conn.execute("INSERT OR REPLACE INTO research (ticker, stage, status, json, updated_at) VALUES (?, ?, ?, ?, ?)",
                         (ticker, stage, status, payload, now_text()))
            conn.commit()
            conn.close()
            return
        except sqlite3.OperationalError as e:
            print("   DB busy saving", ticker, stage, "(attempt", attempt + 1, "):", str(e)[:60])
            time.sleep(1 + attempt)
    print("   could not save", ticker, stage, status, "after 5 attempts")


def load_stages(ticker):
    conn = get_conn()
    rows = conn.execute("SELECT stage, status, json, updated_at FROM research WHERE ticker = ?", (ticker,)).fetchall()
    conn.close()
    stages = {}
    for stage, status, data, updated_at in rows:
        stages[stage] = {"status": status, "updated_at": updated_at, "data": json.loads(data) if data else None}
    return stages


def minutes_since(text):
    """Minutes since a stored timestamp (ISO with offset, or the older naive 'YYYY-MM-DD HH:MM:SS')."""
    try:
        when = datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return 1e9
    if when.tzinfo is None:
        return (datetime.now() - when).total_seconds() / 60
    return (datetime.now().astimezone() - when).total_seconds() / 60


# ---------- quota ----------

def is_quota_error(error):
    text = str(error).lower()
    return "429" in text or "quota" in text or "every model is out" in text or "resource_exhausted" in text


def quota_message():
    return "Daily free LLM quota used up; this stage resumes automatically after the reset (midnight Pacific, ~13:30 IST)."


# ---------- stages ----------

def run_stage(ticker, stage, name):
    """Run one stage, save its result, return its status."""
    save_stage(ticker, stage, "running", None)
    started = time.time()
    try:
        if stage == "financials":
            data = build_numbers(ticker)
        elif stage == "transcripts":
            data = get_transcripts(ticker, n=5)
        elif stage == "guidance":
            data = extract_guidance(ticker)
            if data is not None:
                data = {"ticker": data["ticker"], "name": data["name"], "items": data["items"], "stats": data["stats"]}
        elif stage == "promises":
            data = build_scorecard(ticker)
        else:
            data = build_story(ticker)
        if data is None:
            save_stage(ticker, stage, "not_found", {"message": ticker + " is not on screener"})
            return "not_found"
        data["seconds"] = round(time.time() - started, 1)
        save_stage(ticker, stage, "done", data)
        return "done"
    except Exception as e:
        if is_quota_error(e):
            print("  ", ticker, stage, "-> waiting_quota:", str(e)[:80])
            save_stage(ticker, stage, "waiting_quota", {"message": quota_message(), "detail": str(e)[:200]})
            return "waiting_quota"
        print("  ", ticker, stage, "-> error:", repr(e)[:120])
        save_stage(ticker, stage, "error", {"message": "The AI service was busy or unreachable. Reopen this page in about 10 minutes and this part is retried.",
                                            "detail": repr(e)[:200]})
        return "error"


def stage_needs_run(info):
    """A stage runs if it has never finished, or if its last attempt stalled long enough ago."""
    if info is None:
        return True
    if info["status"] in ("done", "not_found"):
        return False
    if info["status"] == "running":
        # a stage left "running" by a crashed process: retry after a while
        return minutes_since(info["updated_at"]) > RETRY_AFTER_MINUTES
    return minutes_since(info["updated_at"]) > RETRY_AFTER_MINUTES or info["status"] == "pending"


def build_research(ticker, stages=None, force=False):
    """Run the stages that still need running, in order. Returns the statuses."""
    ticker = ticker.upper().strip()
    company = get_company(ticker)
    if company is None:
        for stage in STAGES:
            save_stage(ticker, stage, "not_found", {"message": ticker + " is not on screener"})
        return {stage: "not_found" for stage in STAGES}
    current = load_stages(ticker)
    statuses = {}
    for stage in (stages or STAGES):
        info = current.get(stage)
        if not force and not stage_needs_run(info):
            statuses[stage] = info["status"]
            continue
        try:
            statuses[stage] = run_stage(ticker, stage, company["name"])
        except Exception as e:              # a build thread must never die quietly
            print("  ", ticker, stage, "-> unexpected:", repr(e)[:120])
            save_stage(ticker, stage, "error", {"message": "The AI service was busy or unreachable. Reopen this page in about 10 minutes and this part is retried.",
                                                "detail": repr(e)[:200]})
            statuses[stage] = "error"
        if statuses[stage] == "waiting_quota":
            # the stages after this one need the LLM too: mark them so the client knows
            for later in STAGES[STAGES.index(stage) + 1:]:
                if later in LLM_STAGES:
                    save_stage(ticker, later, "waiting_quota", {"message": quota_message()})
                    statuses[later] = "waiting_quota"
            break
    return statuses


def start_research(ticker):
    """First request for a ticker: numbers now (seconds), the rest in the background.
    One build thread per ticker at a time. Returns False if the ticker is unknown."""
    ticker = ticker.upper().strip()
    company = get_company(ticker)
    if company is None:
        for stage in STAGES:
            save_stage(ticker, stage, "not_found", {"message": ticker + " is not on screener"})
        return False
    current = load_stages(ticker)
    for stage in STAGES:
        if stage not in current:
            save_stage(ticker, stage, "pending", None)
    if stage_needs_run(current.get("financials")):
        run_stage(ticker, "financials", company["name"])
    with _lock:
        if ticker in _building:
            return True
        _building.add(ticker)

    def worker():
        try:
            build_research(ticker)
        finally:
            with _lock:
                _building.discard(ticker)

    threading.Thread(target=worker, daemon=True).start()
    return True


def is_building(ticker):
    with _lock:
        return ticker.upper() in _building


def needs_build(ticker):
    """Is there any stage that should run now? (Polling a ticker whose stages are done, or
    failed less than 10 minutes ago, must not start a thread.)"""
    current = load_stages(ticker.upper().strip())
    if not current:
        return True
    for stage in STAGES:
        if stage_needs_run(current.get(stage)):
            return True
    return False


# ---------- what the API returns ----------

def progress_line(stages):
    ready = []
    for stage, label in (("financials", "numbers"), ("transcripts", "transcripts"), ("guidance", "guidance"), ("promises", "scorecard"), ("story", "story")):
        if stages.get(stage, {}).get("status") == "done":
            ready.append(label)
    running = [s for s in STAGES if stages.get(s, {}).get("status") == "running"]
    waiting = [s for s in STAGES if stages.get(s, {}).get("status") == "waiting_quota"]
    errors = [s for s in STAGES if stages.get(s, {}).get("status") == "error"]
    parts = []
    if ready:
        parts.append("Ready: " + ", ".join(ready))
    if running:
        parts.append("working on " + running[0] + "...")
    elif waiting:
        parts.append("waiting for the daily LLM quota (" + ", ".join(waiting) + ")")
    elif errors:
        parts.append("the AI service was busy for " + ", ".join(errors) + "; it retries on the next visit after 10 minutes")
    if not parts:
        parts.append("Starting...")
    return " - ".join(parts)


def overall_status(stages):
    statuses = [stages.get(s, {}).get("status", "pending") for s in STAGES]
    if all(s == "not_found" for s in statuses):
        return "not_found"
    if all(s == "done" for s in statuses):
        return "done"
    if any(s == "running" for s in statuses) or any(s == "pending" for s in statuses):
        return "building"
    if any(s == "waiting_quota" for s in statuses):
        return "waiting_quota"
    if any(s == "error" for s in statuses):
        return "partial"
    return "building"


def get_research(ticker):
    """Everything the API needs, from the DB only (no network, no LLM). None if never requested."""
    ticker = ticker.upper().strip()
    stages = load_stages(ticker)
    if not stages:
        return None
    sections = {}
    name = None
    for stage in STAGES:
        info = stages.get(stage)
        if info and info["status"] == "done" and info["data"] is not None:
            sections[stage] = info["data"]
            name = name or info["data"].get("name")
    status = overall_status(stages)
    if is_building(ticker) and status in ("waiting_quota", "partial", "done"):
        status = "building"
    return {
        "ticker": ticker, "name": name, "status": status, "progress": progress_line(stages),
        "stages": {s: {"status": stages.get(s, {}).get("status", "pending"), "updated_at": stages.get(s, {}).get("updated_at"),
                       "message": (stages.get(s, {}).get("data") or {}).get("message") if stages.get(s, {}).get("status") in ("waiting_quota", "error", "not_found") else None}
                   for s in STAGES},
        "sections": sections,
        "as_of": max((stages[s]["updated_at"] for s in stages if stages[s].get("updated_at")), default=None),
    }


def valid_ticker(ticker):
    return bool(TICKER_PATTERN.match((ticker or "").upper().strip()))


# ---------- CLI ----------

def print_status(ticker):
    r = get_research(ticker)
    if r is None:
        print(ticker, "-> never requested")
        return
    print("\n==", r["ticker"], "|", r["name"], "|", r["status"], "|", r["progress"])
    for s in STAGES:
        info = r["stages"][s]
        size = len(json.dumps(r["sections"].get(s, {}), default=str)) if s in r["sections"] else 0
        print("  ", s.ljust(12), info["status"].ljust(14), str(info["updated_at"]).ljust(20), (str(size) + " chars") if size else "", info.get("message") or "")


if __name__ == "__main__":
    for symbol in sys.argv[1:] or ["TCS"]:
        started = time.time()
        statuses = build_research(symbol)
        print(symbol, "->", statuses, "in", round(time.time() - started, 1), "s")
        print_status(symbol)
    size = os.path.getsize(os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "finn.db"))
    print("\nfinn.db:", round(size / 1024), "KB")
