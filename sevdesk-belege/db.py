"""SQLite: Protokoll aller Schreibvorgänge, Läufe, Review-Entscheidungen. Kein Cache von sevDesk-Daten."""
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from shared.db import connect as shared_connect

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs(id INTEGER PRIMARY KEY, start TEXT, ende TEXT, dry_run INTEGER,
    erledigt INTEGER, review INTEGER, ohne_beleg INTEGER);
CREATE TABLE IF NOT EXISTS actions(id INTEGER PRIMARY KEY, run_id INTEGER, ts TEXT, objekt_typ TEXT,
    objekt_id TEXT, aktion TEXT, payload_json TEXT, ergebnis TEXT, fehler TEXT, dry_run INTEGER);
CREATE TABLE IF NOT EXISTS review(id INTEGER PRIMARY KEY, art TEXT, beleg_id TEXT, umsatz_id TEXT,
    grund TEXT, status TEXT, entschieden_am TEXT, UNIQUE(art, beleg_id, umsatz_id));
"""


def _jetzt() -> str:
    return datetime.now().isoformat(timespec="seconds")


def init(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def connect(module_dir: Path) -> sqlite3.Connection:
    conn = shared_connect(module_dir)
    init(conn)
    return conn


def run_start(conn, dry_run: bool) -> int:
    cur = conn.execute("INSERT INTO runs(start, dry_run) VALUES (?, ?)", (_jetzt(), int(dry_run)))
    conn.commit()
    return cur.lastrowid


def run_ende(conn, run_id: int, zahlen: dict) -> None:
    conn.execute("UPDATE runs SET ende=?, erledigt=?, review=?, ohne_beleg=? WHERE id=?",
                 (_jetzt(), zahlen.get("sicher", 0), zahlen.get("review", 0), zahlen.get("ohne_beleg", 0), run_id))
    conn.commit()


def log_geplant(conn, run_id, objekt_typ, objekt_id, aktion, payload, dry_run) -> int:
    cur = conn.execute(
        "INSERT INTO actions(run_id, ts, objekt_typ, objekt_id, aktion, payload_json, ergebnis, dry_run)"
        " VALUES (?, ?, ?, ?, ?, ?, 'geplant', ?)",
        (run_id, _jetzt(), objekt_typ, str(objekt_id), aktion, json.dumps(payload, default=str), int(dry_run)))
    conn.commit()
    return cur.lastrowid


def log_ergebnis(conn, action_id: int, ergebnis: str, fehler: str | None = None) -> None:
    conn.execute("UPDATE actions SET ergebnis=?, fehler=? WHERE id=?", (ergebnis, fehler, action_id))
    conn.commit()


def review_merken(conn, art, beleg_id, umsatz_id, grund, status) -> None:
    conn.execute(
        "INSERT INTO review(art, beleg_id, umsatz_id, grund, status, entschieden_am) VALUES (?, ?, ?, ?, ?, ?)"
        " ON CONFLICT(art, beleg_id, umsatz_id) DO UPDATE SET grund=excluded.grund, status=excluded.status,"
        " entschieden_am=excluded.entschieden_am",
        (art, str(beleg_id or ""), str(umsatz_id or ""), grund, status, _jetzt()))
    conn.commit()


def abgelehnt(conn) -> set[tuple[str, str, str]]:
    rows = conn.execute("SELECT art, beleg_id, umsatz_id FROM review WHERE status='abgelehnt'").fetchall()
    return {(r["art"], r["beleg_id"], r["umsatz_id"]) for r in rows}


def letzte_runs(conn, n: int = 5) -> list:
    return conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (n,)).fetchall()
