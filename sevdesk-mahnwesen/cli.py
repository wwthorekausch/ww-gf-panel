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


MAHN_PFAD = "Invoice/Factory/createInvoiceReminder"   # einziger Schreibpfad: Mahnung als Entwurf anlegen


def cmd_mahnung_entwurf(args, config) -> None:
    """Mahnungs-Entwurf (Typ MA) für eine Rechnung anlegen — nur wenn laut Mahnliste fällig. Versendet nichts."""
    import json
    cmd_sync(args, config)
    conn = db.connect()
    rechnungen, info = _aus_db(conn)
    r = next((x for x in rechnungen if x.nummer.upper() == args.rechnung.upper() or x.nummer.upper().endswith(args.rechnung.upper())), None)
    if r is None:
        print(f"{args.rechnung}: nicht unter den offenen Rechnungen ab 2025 (oder ausgeblendet).")
        return
    pfad = MODULE_DIR / "mahn_absprachen.json"
    absprachen = json.loads(pfad.read_text(encoding="utf-8")) if pfad.exists() else []
    ok, grund, stufe = mahnwesen.mahnbar(r, info.get(r.id), absprachen, date.today())
    print(f"{r.nummer}  {r.kunde}  offen {_eur(r.offen).strip()}  fällig {r.faellig:%d.%m.%Y}  sevDesk-Stufe {r.stufe}")
    if not ok:
        print(f"Kein Entwurf: {grund}")
        return
    print(f"Anlegen: {grund} als Entwurf (wird NICHT versendet).")
    if args.dry_run:
        print("DRY-RUN — nichts geschrieben")
        return
    if input("Entwurf anlegen? [j/N] ").strip().lower() != "j":
        return
    client = build_client(config)
    vorher = {str(m["id"]) for m in _alle(client, {"invoiceType": "MA"}) if str((m.get("origin") or {}).get("id")) == r.id}
    client._request("POST", MAHN_PFAD, params={"invoice[id]": int(r.id), "invoice[objectName]": "Invoice"},
                    json={"invoice": {"id": int(r.id), "objectName": "Invoice"}})
    neu = [m for m in _alle(client, {"invoiceType": "MA"})
           if str((m.get("origin") or {}).get("id")) == r.id and str(m["id"]) not in vorher]
    if not neu:
        print("WARNUNG: kein neuer Mahnungs-Entwurf gefunden — in sevDesk prüfen.")
        return
    m = neu[0]
    print(f"Angelegt: Mahnung {m.get('invoiceNumber') or m['id']} (ID {m['id']}), Stufe {m.get('dunningLevel')}, "
          f"Status {m.get('status')}, Frist {(m.get('reminderDeadline') or '')[:10]}, Betrag {m.get('reminderTotal')}")


def cmd_mahnung_senden(args, config) -> None:
    """Mahnungs-Entwurf einer Rechnung per E-Mail (sevDesk sendViaEmail, PDF im Anhang) — nur nach Vorschau + 'j'."""
    import json
    import re
    client = build_client(config)
    nr = args.rechnung.upper() if args.rechnung.upper().startswith("RE-") else f"RE-{args.rechnung}"
    orig_roh = [x for x in client.get("Invoice", params={"invoiceNumber": nr, "embed": "contact"})["objects"]
                if x.get("invoiceType") != "MA"]
    if len(orig_roh) != 1:
        print(f"{nr}: Rechnung nicht eindeutig gefunden.")
        return
    original = mahnwesen.parse(orig_roh[0])
    entwuerfe = [m for m in _alle(client, {"invoiceType": "MA"})
                 if str((m.get("origin") or {}).get("id")) == original.id and int(m.get("status") or 0) < 200]
    if len(entwuerfe) != 1:
        print(f"{nr}: {len(entwuerfe)} Mahnungs-Entwürfe gefunden — erwartet genau einen (erst mahnung-entwurf).")
        return
    ma = entwuerfe[0]
    pfad = MODULE_DIR / "mahn_absprachen.json"
    absprachen = json.loads(pfad.read_text(encoding="utf-8")) if pfad.exists() else []
    ok, grund = mahnwesen.sendbar(ma, original, absprachen)
    if not ok:
        print(f"Nicht versendet: {grund}")
        return
    an = args.an
    if not an:
        kid = (orig_roh[0].get("contact") or {}).get("id")
        wege = client.get("CommunicationWay", params={"contact[id]": kid, "contact[objectName]": "Contact"})["objects"]
        an = mahnwesen.waehle_mail(wege)
        if not an:
            print(f"E-Mail-Adresse nicht eindeutig ({[w['value'] for w in wege if w.get('type') == 'EMAIL']}) — mit --an angeben "
                  f"oder in sevDesk eine Adresse als 'Rechnungsadresse' markieren.")
            return
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", an or ""):
        print(f"Ungültige E-Mail-Adresse: {an}")
        return
    frist = date.fromisoformat((ma.get("reminderDeadline") or original.faellig.isoformat())[:10])
    if args.neue_frist:
        neu = date.fromisoformat(args.neue_frist)
        ok, grund = mahnwesen.neue_frist_ok(frist, neu, date.today())
        if not ok:
            print(f"Frist nicht geändert: {grund}")
            return
        if args.dry_run:
            print(f"(dry-run) Frist würde {frist:%d.%m.%Y} → {neu:%d.%m.%Y} gesetzt")
        else:
            vorher = (ma.get("sumGross"), ma.get("dunningLevel"), ma.get("origin", {}).get("id"))
            client.put(f"Invoice/{int(ma['id'])}", json={"reminderDeadline": neu.isoformat()})
            ma = client.get(f"Invoice/{ma['id']}")["objects"][0]
            nachher = (ma.get("sumGross"), ma.get("dunningLevel"), ma.get("origin", {}).get("id"))
            if (ma.get("reminderDeadline") or "")[:10] != neu.isoformat() or vorher != nachher or int(ma.get("status") or 0) >= 200:
                print(f"STOPP: Entwurf nach Friständerung unerwartet ({ma.get('reminderDeadline')}, {nachher}) — nicht versendet")
                return
            print(f"Frist gesetzt: {frist:%d.%m.%Y} → {neu:%d.%m.%Y} (Entwurf nachgelesen, Betrag/Stufe unverändert)")
        frist = neu
    elif frist < date.today():
        print(f"Frist der Mahnung {frist:%d.%m.%Y} ist abgelaufen — mit --neue-frist JJJJ-MM-TT neu setzen.")
        return
    stufe = int(ma.get("dunningLevel") or 1)
    mail = mahnwesen.mahn_mail(original.nummer, original.datum, original.offen, frist, stufe)
    print(f"Mahnung ID {ma['id']} (Stufe {stufe}) zu {original.nummer}, {original.kunde}, offen {_eur(original.offen).strip()}")
    print(f"An:      {an}\nBetreff: {mail['subject']}\nAnhang:  Mahnung als PDF (sevDesk)\n")
    print(re.sub(r"<br>", "\n", re.sub(r"</?b>", "", mail["text"])))
    if args.dry_run:
        print("\nDRY-RUN — nichts versendet")
        return
    if input("\nJetzt per E-Mail versenden? [j/N] ").strip().lower() != "j":
        print("nicht versendet")
        return
    client._request("POST", f"Invoice/{int(ma['id'])}/sendViaEmail",
                    json={"toEmail": an, "subject": mail["subject"], "text": mail["text"], "copy": False,
                          "additionalAttachments": None, "ccEmail": None, "bccEmail": None, "sendXml": False})
    nach = client.get(f"Invoice/{ma['id']}")["objects"][0]
    print(f"Versendet: Status {nach.get('status')}, sendDate {nach.get('sendDate')}, sendType {nach.get('sendType')}")


VERZICHT_KONTO = 4842223   # Offline-Konto "Kein Beleg / Vertrag" — 0-€-Protokollbuchung


def cmd_mahngebuehr_erlassen(args, config) -> None:
    """Offene Mahngebühren bezahlter Rechnungen per Minderung (bookAmount 0 €, Typ O) abschließen. Kein Geldfluss."""
    client = build_client(config)
    kandidaten = []
    for ma in _alle(client, {"invoiceType": "MA", "status": 750}):
        if ma.get("invoiceType") != "MA":
            continue
        orig = client.get(f"Invoice/{ma['origin']['id']}")["objects"][0]
        ok, grund = mahnwesen.gebuehr_erlassbar(ma, orig)
        (kandidaten.append((ma, orig)) if ok else print(f"  übersprungen MA {ma['id']} zu {orig.get('invoiceNumber')}: {grund}"))
    summe = sum((mahnwesen._dec(ma.get("reminderCharge")) for ma, _ in kandidaten), start=mahnwesen.Decimal("0"))
    print(f"{len(kandidaten)} Mahngebühren erlassbar, zusammen {_eur(summe).strip()}")
    if args.dry_run or not kandidaten:
        print("DRY-RUN — nichts gebucht" if args.dry_run else "")
        return
    if input(f"{min(len(kandidaten), args.limit)} Mahngebühren als Minderung abschließen? [j/N] ").strip().lower() != "j":
        return
    erledigt = 0
    for ma, orig in kandidaten[: args.limit]:
        client.put(f"Invoice/{int(ma['id'])}/bookAmount",
                   json={"amount": 0, "date": date.today().isoformat(), "type": "O",
                         "checkAccount": {"id": VERZICHT_KONTO, "objectName": "CheckAccount"}, "createFeed": False})
        nach = client.get(f"Invoice/{ma['id']}")["objects"][0]
        o2 = client.get(f"Invoice/{orig['id']}")["objects"][0]
        if str(nach.get("status")) != "1000" or str(o2.get("status")) != "1000" or mahnwesen._dec(nach.get("paidAmount")) != 0:
            print(f"STOPP bei MA {ma['id']} ({orig.get('invoiceNumber')}): Status {nach.get('status')}, Rechnung {o2.get('status')}")
            break
        erledigt += 1
    print(f"erledigt: {erledigt} Mahngebühren erlassen (Rechnungen unverändert)")


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

    p = sub.add_parser("mahnung-entwurf", help="Mahnungs-Entwurf für eine fällige Rechnung anlegen (versendet nicht)")
    p.add_argument("rechnung", help="Rechnungsnummer, z.B. RE-27319 oder 27319")
    p.add_argument("--dry-run", action="store_true")
    p = sub.add_parser("mahnung-senden", help="Mahnungs-Entwurf per E-Mail versenden (nach Vorschau + j)")
    p.add_argument("rechnung", help="Rechnungsnummer, z.B. RE-27276")
    p.add_argument("--an", help="Empfänger-E-Mail (sonst aus dem Kontakt)")
    p.add_argument("--neue-frist", help="abgelaufene Frist im Entwurf neu setzen (JJJJ-MM-TT)")
    p.add_argument("--dry-run", action="store_true")
    p = sub.add_parser("mahngebuehr-erlassen", help="offene Mahngebühren bezahlter Rechnungen als Minderung abschließen")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--limit", type=int, default=100)
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
        "mahnung-entwurf": cmd_mahnung_entwurf,
        "mahnung-senden": cmd_mahnung_senden,
        "mahngebuehr-erlassen": cmd_mahngebuehr_erlassen,
    }
    handlers[args.command](args, config)
    return 0


if __name__ == "__main__":
    sys.exit(main())
