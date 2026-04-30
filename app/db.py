import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "app.db"


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                phone_number TEXT NOT NULL,
                intent       TEXT,
                amount       INTEGER,
                category     TEXT,
                description  TEXT,
                created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()


def insert_transaction(
    phone_number: str,
    intent: str,
    amount: int,
    category: str,
    description: str,
) -> int:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO transactions (phone_number, intent, amount, category, description) VALUES (?, ?, ?, ?, ?)",
        (phone_number, intent, amount, category, description),
    )
    conn.commit()
    tx_id = cur.lastrowid
    conn.close()
    return tx_id


def get_transactions(phone_number: str) -> list[sqlite3.Row]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM transactions WHERE phone_number = ? ORDER BY created_at ASC",
            (phone_number,),
        ).fetchall()
    return rows
