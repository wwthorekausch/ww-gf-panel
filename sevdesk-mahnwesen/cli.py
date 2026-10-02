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
    db.snapshot(conn, rechnungen, mahnwesen.gemahnt(mahnungen), mahnwesen.letzte_mahnungen(mahnungen),
                datetime.now(timezone.utc).isoformat())
    print(f"{len(rechnungen)} offene Rechnung(en) ab {mahnwesen.STICHTAG:%d.%m.%Y}, {len(mahnungen)} Mahnung(en) synchronisiert.")


def _aus_db(conn):
    from decimal import Decimal
    zeilen = db.lade(conn)
    rechnungen = [mahnwesen.Rechnung(id=r["id"], nummer=r["nummer"], kunde=r["kunde"], kundennummer=r["kundennummer"],
                                     datum=date.fromisoformat(r["datum"]), faellig=date.fromisoformat(r["faellig"]),
                                     brutto=Decimal(str(r["brutto"])), offen=Decimal(str(r["offen"])), typ=r["typ"],
                                     status=r["status"], stufe=r["stufe"]) for r in zeilen]
    info = {r["id"]: mahnwesen.MahnInfo(stufe=r["mahn_stufe"], frist=date.fromisoformat(r["mahn_frist"]) if r["mahn_frist"] else None,
                                        entwurf=bool(r["mahn_entwurf"])) for r in zeilen if r["mahn_stufe"] is not None}
    return rechnungen, info


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
    """Was ist zu tun? Laut sevDesk (dunningLevel, reminderDeadline der letzten Mahnung, Entwurf) — keine festen Tage."""
    if args.sync:
        cmd_sync(args, config)
    conn = db.connect()
    rechnungen, info = _aus_db(conn)
    heute = date.today()
    import json
    pfad = MODULE_DIR / "mahn_absprachen.json"
    absprachen = json.loads(pfad.read_text(encoding="utf-8")) if pfad.exists() else []
    todo, vereinbart = [], []
    for r in rechnungen:
        a = mahnwesen.aktion(r, info.get(r.id), heute)
        if not a:
            continue
        ab = mahnwesen.absprache(r.kunde, absprachen, r.nummer)
        (vereinbart if ab else todo).append((ab, r) if ab else (a, r))
    gruppen = {}
    for a, r in todo:
        gruppen.setdefault((a[0], a[1]), []).append((a, r))
    for (was, stufe) in sorted(gruppen, key=lambda k: (k[0] != "entwurf versenden", -k[1])):
        xs = sorted(gruppen[(was, stufe)], key=lambda t: t[0][2])
        titel = f"Mahnungs-Entwurf Stufe {stufe} versenden" if was == "entwurf versenden" else f"{stufe}. Mahnung erstellen"
        print(f"\n== {titel}: {len(xs)} Rechnung(en), {_eur(sum((r.offen for _, r in xs), start=0)).strip()}")
        for a, r in xs:
            tage = (heute - a[2]).days
            print(f"  {r.nummer:<12} {r.kunde[:34]:<34} Frist {a[2]:%d.%m.%y} ({tage:>4} T)  {_eur(r.offen)}  sevDesk-Stufe {r.stufe}")
    if vereinbart:
        print(f"\n== Absprachen (nicht mahnen): {len(vereinbart)} Rechnung(en), {_eur(sum((r.offen for _, r in vereinbart), start=0)).strip()}")
        for ab, r in sorted(vereinbart, key=lambda t: (t[0]["aktion"], t[1].kunde, t[1].faellig)):
            print(f"  {r.nummer:<12} {r.kunde[:34]:<34} {_eur(r.offen)}  {ab['aktion']}: {ab.get('notiz', '')}")
    print(f"\n{len(todo)} Rechnungen mit Handlungsbedarf, zusammen {_eur(sum((r.offen for _, r in todo), start=0)).strip()}"
          f"  (ab {mahnwesen.STICHTAG:%d.%m.%Y}; Frist = Mahnfrist aus sevDesk bzw. Zahlungsziel; ausgeblendete nicht enthalten)")


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

    for name, hilfe in (("mahnungen", "Handlungsbedarf laut sevDesk-Mahnstufe/-frist"), ("offen", "offener Betrag pro Kunde")):
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
