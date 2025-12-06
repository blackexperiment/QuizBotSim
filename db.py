# db.py
"""
Minimal SQLite DB helper for QuizBot (formatted-questions-only version).

Provides:
- set_db_path(path)
- init_db(owner_tg_id)
- is_sudo(tg_id)
- add_sudo(tg_id, name, added_by)
- remove_sudo(tg_id)
- list_sudos()
- set_default_target(chat_id)
- get_default_target(owner_tg_id)
"""

import os
import sqlite3
import logging
from typing import Optional, List, Dict

logger = logging.getLogger("quizbot.db")
DB_PATH = "./botdata.sqlite"


def set_db_path(path: str):
    """Set database filepath before init_db if you want custom path."""
    global DB_PATH
    DB_PATH = path


def get_conn():
    """Open a new sqlite3 connection (caller must close)."""
    # enable row factory if needed
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    return conn


def init_db(owner_tg_id: int):
    """Create tables and ensure owner exists in sudo_users."""
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    conn = get_conn()
    cur = conn.cursor()

    # sudo users table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sudo_users (
            tg_id INTEGER PRIMARY KEY,
            name TEXT,
            added_by INTEGER,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # settings table (key-value)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );
    """)

    # ensure owner is present as sudo
    cur.execute("SELECT 1 FROM sudo_users WHERE tg_id = ?", (owner_tg_id,))
    if cur.fetchone() is None and owner_tg_id:
        cur.execute("INSERT INTO sudo_users (tg_id, name, added_by) VALUES (?, ?, ?)",
                    (owner_tg_id, "Owner", owner_tg_id))

    conn.commit()
    conn.close()


# ---------- sudo user helpers ----------
def is_sudo(tg_id: int) -> bool:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM sudo_users WHERE tg_id = ?", (tg_id,))
    res = cur.fetchone() is not None
    conn.close()
    return res


def add_sudo(tg_id: int, name: Optional[str], added_by: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT OR IGNORE INTO sudo_users (tg_id, name, added_by)
        VALUES (?, ?, ?)
    """, (tg_id, name, added_by))
    conn.commit()
    conn.close()


def remove_sudo(tg_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM sudo_users WHERE tg_id = ?", (tg_id,))
    conn.commit()
    conn.close()


def list_sudos() -> List[Dict]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT tg_id, name, added_at FROM sudo_users ORDER BY added_at ASC")
    rows = cur.fetchall()
    conn.close()
    return [{"tg_id": r[0], "name": r[1], "added_at": r[2]} for r in rows]


# ---------- settings helpers ----------
def set_default_target(chat_id: int):
    """Set default target chat id where quizzes will be posted."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO settings (key, value)
        VALUES ('default_target', ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
    """, (str(chat_id),))
    conn.commit()
    conn.close()


def get_default_target(owner_tg_id: int) -> int:
    """
    Return default target chat id. If not set, return owner_tg_id as fallback.
    """
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT value FROM settings WHERE key = 'default_target'")
    row = cur.fetchone()
    conn.close()
    if row and row[0]:
        try:
            return int(row[0])
        except Exception:
            return owner_tg_id
    return owner_tg_id
