import os
import sqlite3

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
    # Step 6: one results card per results filing (card = JSON text)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS results_cards (
            announcement_id TEXT PRIMARY KEY,
            symbol TEXT, card TEXT
        )""")
    # Step 7: one management-change card per filing (card = JSON text)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS mgmt_cards (
            announcement_id TEXT PRIMARY KEY,
            symbol TEXT, card TEXT
        )""")
    # Added in Step 5: was this filing classified by a "rule" or by the "llm"?
    try:
        conn.execute("ALTER TABLE announcements ADD COLUMN classified_by TEXT")
    except sqlite3.OperationalError:
        pass   # column already exists
    return conn
