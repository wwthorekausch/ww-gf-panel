"""Gemeinsamer SQLite-Connection-Helper für alle Cockpit-Module."""
import sqlite3
from pathlib import Path


def connect(module_dir: Path, filename: str = "data.db") -> sqlite3.Connection:
    conn = sqlite3.connect(module_dir / filename)
    conn.row_factory = sqlite3.Row
    return conn
