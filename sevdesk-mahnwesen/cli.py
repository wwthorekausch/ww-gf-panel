#!/usr/bin/env python3
"""CLI für sevdesk-mahnwesen: sync, hide, unhide, mahnungen."""
import argparse
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from shared.config import load_config
from shared.keychain import keychain_token
from shared.sevdesk_client import SevdeskClient

import db
import mahnwesen

MODULE_DIR = Path(__file__).parent


def build_client(config) -> SevdeskClient:
    return SevdeskClient(keychain_token("ww-gf-cockpit-sevdesk"))


def _alle(client, params: dict) -> list[dict]:
    out, offset = [], 0
    while True:
        batch = client.get("Invoice", params={**params, "limit": 1000, "offset": offset})["objects"]
        out += batch
        if len(batch) < 1000:
            return out
        offset += 1000


def cmd_sync(args, config) -> None:
    """Nur lesend: offene (200) und teilbezahlte (750) Rechnungen + sevDesk-Mahnungen (Typ MA) holen."""
    client = build_client(config)
    roh = [r for st in (200, 750) for r in _alle(client, {"status": st, "embed": "contact"})]
    mahnungen = [r for r in _alle(client, {"invoiceType": "MA"}) if r.get("invoiceType") == "MA"]
    rechnungen = mahnwesen.ab_stichtag([mahnwesen.parse(r) for r in roh if r.get("invoiceType") != "MA"])
    conn = db.connect()
    db.snapshot(conn, rechnungen, mahnwesen.gemahnt(mahnungen), datetime.now(timezone.utc).isoformat())
    print(f"{len(rechnungen)} offene Rechnung(en) ab {mahnwesen.STICHTAG:%d.%m.%Y}, {len(mahnungen)} Mahnung(en) synchronisiert.")


def _aus_db(conn) -> list:
    from decimal import Decimal
    return [mahnwesen.Rechnung(id=r["id"], nummer=r["nummer"], kunde=r["kunde"], kundennummer=r["kundennummer"],
                               datum=date.fromisoformat(r["datum"]), faellig=date.fromisoformat(r["faellig"]),
                               brutto=Decimal(str(r["brutto"])), offen=Decimal(str(r["offen"])), typ=r["typ"],
                               status=r["status"]) for r in db.lade(conn)], {r["id"]: r["gemahnt"] for r in db.lade(conn)}


def _eur(x) -> str:
    return f"{x:>12,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def cmd_hide(args, config) -> None:
    conn = db.connect()
    db.set_hidden(conn, args.invoice_id, True, datetime.now(timezone.utc).isoformat())

    tag_name = config["tags"]["hidden_tag"]
    client = build_client(config)
    client.add_tag_to_invoice(args.invoice_id, tag_name)
    print(f"Rechnung {args.invoice_id} ausgeblendet (lokal + Tag '{tag_name}' in sevDesk gesetzt).")


def cmd_unhide(args, config) -> None:
    conn = db.connect()
    db.set_hidden(conn, args.invoice_id, False)
    print(f"Rechnung {args.invoice_id} wieder eingeblendet (lokal). Tag in sevDesk bleibt bestehen.")


def cmd_mahnungen(args, config) -> None:
    """Überfällige Rechnungen (Zahlungsziel überschritten), älteste zuerst, mit Mahnstufe."""
    if args.sync:
        cmd_sync(args, config)
    conn = db.connect()
    rechnungen, gemahnt = _aus_db(conn)
    schwellen = tuple(int(config["mahnstufen"][f"stufe_{i}_tage"]) for i in (1, 2, 3))
    heute = date.today()
    xs = mahnwesen.ueberfaellig(rechnungen, heute)
    print(f"{'Rechnung':<12} {'Kunde':<34} {'fällig':<10} {'Tage':>5} {'offen':>15}  Stufe  gemahnt")
    for r in xs:
        tage = mahnwesen.tage_ueberfaellig(r, heute)
        g = gemahnt.get(r.id, 0)
        print(f"{r.nummer:<12} {r.kunde[:34]:<34} {r.faellig:%d.%m.%y} {tage:>5} {_eur(r.offen)}  {mahnwesen.mahnstufe(tage, schwellen):^5}  {g or '-'}")
    print(f"\n{len(xs)} überfällig, zusammen {_eur(sum((r.offen for r in xs), start=0)).strip()}"
          f"  (Stufen ab {schwellen[0]}/{schwellen[1]}/{schwellen[2]} Tagen; ausgeblendete nicht enthalten)")


def cmd_offen(args, config) -> None:
    """Offener Betrag pro Kunde (Gutschriften gegengerechnet), davon überfällig."""
    if args.sync:
        cmd_sync(args, config)
    conn = db.connect()
    rechnungen, _ = _aus_db(conn)
    zeilen = mahnwesen.offen_pro_kunde(rechnungen, date.today())
    print(f"{'Kunde':<40} {'offen':>15} {'davon überfällig':>17}  Belege")
    for kunde, offen, faellig, n in zeilen:
        print(f"{kunde[:40]:<40} {_eur(offen)} {_eur(faellig):>17}  {n:>6}")
    print(f"\n{'Summe':<40} {_eur(sum((z[1] for z in zeilen), start=0))} {_eur(sum((z[2] for z in zeilen), start=0)):>17}")


def main() -> int:
    parser = argparse.ArgumentParser(prog="sevdesk-mahnwesen")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("sync", help="offene Rechnungen von sevDesk holen")

    hide_parser = sub.add_parser("hide", help="Rechnung ausblenden")
    hide_parser.add_argument("invoice_id")

    unhide_parser = sub.add_parser("unhide", help="Ausblenden rückgängig")
    unhide_parser.add_argument("invoice_id")

    for name, hilfe in (("mahnungen", "überfällige Rechnungen mit Mahnstufe"), ("offen", "offener Betrag pro Kunde")):
        p = sub.add_parser(name, help=hilfe)
        p.add_argument("--sync", action="store_true", help="vorher frisch aus sevDesk laden")

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
        "offen": cmd_offen,
    }
    handlers[args.command](args, config)
    return 0


if __name__ == "__main__":
    sys.exit(main())
