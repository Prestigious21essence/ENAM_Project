"""Download EOD prices from Yahoo into SQLite and check price/volume alerts.

Usage:
    python ingest\\prices.py              -> uses thresholds from portfolio.json
    python ingest\\prices.py 0.5 1.0      -> override: price_move_pct=0.5, volume_multiple=1.0
"""
import json
import math
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
        df = yf.Ticker(symbol + ".NS").history(period=period, auto_adjust=False)
        if df.empty:
            print("No data for", symbol)
            continue

        saved = 0
        for date, row in df.iterrows():
            # Skip rows Yahoo sometimes returns with missing values
            if math.isnan(row["Close"]) or math.isnan(row["Volume"]):
                continue
            conn.execute(
                "INSERT OR REPLACE INTO prices VALUES (?, ?, ?, ?, ?, ?, ?)",
                (symbol, date.strftime("%Y-%m-%d"),
                 float(row["Open"]), float(row["High"]), float(row["Low"]),
                 float(row["Close"]), int(row["Volume"])),
            )
            saved = saved + 1
        conn.commit()
        print(symbol, "->", saved, "days, last date", df.index[-1].strftime("%Y-%m-%d"))
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

    previous_volumes = []
    for r in rows[1:]:
        previous_volumes.append(r[2])
    avg_volume = sum(previous_volumes) / len(previous_volumes)

    if avg_volume > 0:
        volume_ratio = today_volume / avg_volume
    else:
        volume_ratio = 0

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
    symbols = []
    for c in data["portfolio"]:
        symbols.append(c["symbol"])

    price_move_pct = settings["price_move_pct"]
    volume_multiple = settings["volume_multiple"]
    if len(sys.argv) == 3:
        price_move_pct = float(sys.argv[1])
        volume_multiple = float(sys.argv[2])

    download_prices(symbols)

    print("\n--- Alerts (price >=", price_move_pct, "%, volume >=", volume_multiple, "x) ---")
    count = 0
    for s in symbols:
        for a in check_alerts(s, price_move_pct, volume_multiple, settings["volume_window_days"]):
            print(a)
            count = count + 1
    print("Total alerts:", count)
