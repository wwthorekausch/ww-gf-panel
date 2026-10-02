"""SQLite: Snapshot offener Rechnungen (bei jedem sync neu) + dauerhaft ausgeblendete Rechnungen."""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from shared.db import connect as shared_connect

MODULE_DIR = Path(__file__).parent

SCHEMA = """
CREATE TABLE IF NOT EXISTS rechnungen (
    id TEXT PRIMARY KEY, nummer TEXT, kunde TEXT, kundennummer TEXT, datum TEXT, faellig TEXT,
    brutto REAL, offen REAL, typ TEXT, status INTEGER, gemahnt INTEGER NOT NULL DEFAULT 0, zuletzt_gesehen TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ausgeblendet (id TEXT PRIMARY KEY, seit TEXT);
"""


def connect() -> sqlite3.Connection:
    conn = shared_connect(MODULE_DIR)
    conn.executescript(SCHEMA)
    return conn


def snapshot(conn, rechnungen: list, gemahnt: dict[str, int], seen_at: str) -> None:
    conn.execute("DELETE FROM rechnungen")
    conn.executemany(
        "INSERT INTO rechnungen VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [(r.id, r.nummer, r.kunde, r.kundennummer, r.datum.isoformat(), r.faellig.isoformat(), float(r.brutto),
          float(r.offen), r.typ, r.status, gemahnt.get(r.id, 0), seen_at) for r in rechnungen])
    conn.commit()


def lade(conn, mit_ausgeblendeten: bool = False) -> list[sqlite3.Row]:
    q = "SELECT * FROM rechnungen"
    if not mit_ausgeblendeten:
        q += " WHERE id NOT IN (SELECT id FROM ausgeblendet)"
    return conn.execute(q + " ORDER BY faellig").fetchall()


def set_hidden(conn, invoice_id: str, hidden: bool, seit: str = "") -> None:
    if hidden:
        conn.execute("INSERT OR IGNORE INTO ausgeblendet VALUES (?, ?)", (invoice_id, seit))
    else:
        conn.execute("DELETE FROM ausgeblendet WHERE id = ?", (invoice_id,))
    conn.commit()
