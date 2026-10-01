#!/usr/bin/env python3
"""CLI für sevdesk-mahnwesen: sync, hide, unhide, mahnungen."""
import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from shared.config import load_config
from shared.sevdesk_client import SevdeskClient

import db

MODULE_DIR = Path(__file__).parent


def build_client(config) -> SevdeskClient:
    return SevdeskClient(config["sevdesk"]["api_token"])


def cmd_sync(args, config) -> None:
    client = build_client(config)
    conn = db.connect()
    invoices = client.get_open_invoices()
    now = datetime.now(timezone.utc).isoformat()

    for inv in invoices:
        db.upsert_invoice(
            conn,
            {
                "id": inv["id"],
                "kunde": (inv.get("contact") or {}).get("name") or (inv.get("contact") or {}).get("id", "?"),
                "betrag": float(inv.get("sumGross") or 0),
                "faelligkeitsdatum": inv.get("payDate") or inv.get("dueDate") or "",
                "status": inv.get("status", ""),
            },
            now,
        )
    conn.commit()
    print(f"{len(invoices)} offene Rechnung(en) synchronisiert.")


def cmd_hide(args, config) -> None:
    conn = db.connect()
    db.set_hidden(conn, args.invoice_id, True)

    tag_name = config["tags"]["hidden_tag"]
    client = build_client(config)
    client.add_tag_to_invoice(args.invoice_id, tag_name)
    print(f"Rechnung {args.invoice_id} ausgeblendet (lokal + Tag '{tag_name}' in sevDesk gesetzt).")


def cmd_unhide(args, config) -> None:
    conn = db.connect()
    db.set_hidden(conn, args.invoice_id, False)
    print(f"Rechnung {args.invoice_id} wieder eingeblendet (lokal). Tag in sevDesk bleibt bestehen.")


def cmd_mahnungen(args, config) -> None:
    print("Noch nicht implementiert.")


def main() -> int:
    parser = argparse.ArgumentParser(prog="sevdesk-mahnwesen")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("sync", help="offene Rechnungen von sevDesk holen")

    hide_parser = sub.add_parser("hide", help="Rechnung ausblenden")
    hide_parser.add_argument("invoice_id")

    unhide_parser = sub.add_parser("unhide", help="Ausblenden rückgängig")
    unhide_parser.add_argument("invoice_id")

    sub.add_parser("mahnungen", help="Übersicht mit Mahnstufen")

    args = parser.parse_args()

    try:
        config = load_config(MODULE_DIR)
    except FileNotFoundError as e:
        print(e)
        return 1

    handlers = {
        "sync": cmd_sync,
        "hide": cmd_hide,
        "unhide": cmd_unhide,
        "mahnungen": cmd_mahnungen,
    }
    handlers[args.command](args, config)
    return 0


if __name__ == "__main__":
    sys.exit(main())
