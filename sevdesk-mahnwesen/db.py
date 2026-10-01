"""SQLite-Schema und Queries für offene Rechnungen."""
import sqlite3
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from shared.db import connect as shared_connect

MODULE_DIR = Path(__file__).parent

SCHEMA = """
CREATE TABLE IF NOT EXISTS invoices (
    id TEXT PRIMARY KEY,
    kunde TEXT,
    betrag REAL,
    faelligkeitsdatum TEXT,
    status TEXT,
    hidden INTEGER NOT NULL DEFAULT 0,
    zuletzt_gesehen TEXT NOT NULL
);
"""


def connect() -> sqlite3.Connection:
    conn = shared_connect(MODULE_DIR)
    conn.execute(SCHEMA)
    conn.commit()
    return conn


def upsert_invoice(conn: sqlite3.Connection, invoice: dict, seen_at: str) -> None:
    conn.execute(
        """
        INSERT INTO invoices (id, kunde, betrag, faelligkeitsdatum, status, zuletzt_gesehen)
        VALUES (:id, :kunde, :betrag, :faelligkeitsdatum, :status, :zuletzt_gesehen)
        ON CONFLICT(id) DO UPDATE SET
            kunde = excluded.kunde,
            betrag = excluded.betrag,
            faelligkeitsdatum = excluded.faelligkeitsdatum,
            status = excluded.status,
            zuletzt_gesehen = excluded.zuletzt_gesehen
        """,
        {**invoice, "zuletzt_gesehen": seen_at},
    )


def set_hidden(conn: sqlite3.Connection, invoice_id: str, hidden: bool) -> None:
    conn.execute("UPDATE invoices SET hidden = ? WHERE id = ?", (int(hidden), invoice_id))
    conn.commit()


def list_open_invoices(conn: sqlite3.Connection, include_hidden: bool = False) -> list[sqlite3.Row]:
    query = "SELECT * FROM invoices"
    if not include_hidden:
        query += " WHERE hidden = 0"
    query += " ORDER BY faelligkeitsdatum ASC"
    return conn.execute(query).fetchall()
