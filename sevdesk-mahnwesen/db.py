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
    brutto REAL, offen REAL, typ TEXT, status INTEGER, gemahnt INTEGER NOT NULL DEFAULT 0, zuletzt_gesehen TEXT NOT NULL,
    stufe INTEGER NOT NULL DEFAULT 0, mahn_stufe INTEGER, mahn_frist TEXT, mahn_entwurf INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS ausgeblendet (id TEXT PRIMARY KEY, seit TEXT);
"""


def connect() -> sqlite3.Connection:
    conn = shared_connect(MODULE_DIR)
    spalten = {r[1] for r in conn.execute("PRAGMA table_info(rechnungen)")}
    if spalten and "mahn_frist" not in spalten:
        conn.execute("DROP TABLE rechnungen")      # reiner Snapshot, wird beim nächsten sync neu gefüllt
    conn.executescript(SCHEMA)
    return conn


def snapshot(conn, rechnungen: list, gemahnt: dict[str, int], info: dict, seen_at: str) -> None:
    conn.execute("DELETE FROM rechnungen")
    zeilen = []
    for r in rechnungen:
        i = info.get(r.id)
        zeilen.append((r.id, r.nummer, r.kunde, r.kundennummer, r.datum.isoformat(), r.faellig.isoformat(), float(r.brutto),
                       float(r.offen), r.typ, r.status, gemahnt.get(r.id, 0), seen_at, r.stufe,
                       i.stufe if i else None, i.frist.isoformat() if i and i.frist else None, int(bool(i and i.entwurf))))
    conn.executemany("INSERT INTO rechnungen VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", zeilen)
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
