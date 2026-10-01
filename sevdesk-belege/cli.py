#!/usr/bin/env python3
"""CLI für sevdesk-belege: run, review, status, init-regeln. Harte Regeln: siehe CLAUDE.md im Root."""
import argparse
import configparser
import json
import sys
from dataclasses import asdict
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from shared.keychain import keychain_token
from shared.sevdesk_client import SevdeskClient

import actions
import db
import laden
import rules
from modell import Fall, Grenzen, LieferantWissen, Standardregel

MODULE_DIR = Path(__file__).parent
REGELN_PFAD = MODULE_DIR / "standardbuchungen.json"
FEST_PFAD = MODULE_DIR / "lieferanten.json"      # von Hand festgelegte Kategorien (gitignored)
KEYCHAIN_SERVICE = "ww-gf-cockpit-sevdesk"


def lade_grenzen(config: configparser.ConfigParser) -> Grenzen:
    g = config["grenzen"] if config.has_section("grenzen") else {}
    d = Grenzen()
    ids = config.get("kategorien", "standard_ids", fallback="")
    return Grenzen(
        usd_toleranz_prozent=Decimal(g.get("usd_toleranz_prozent", str(d.usd_toleranz_prozent))),
        tage_vorher=int(g.get("tage_vorher", d.tage_vorher)),
        tage_nachher=int(g.get("tage_nachher", d.tage_nachher)),
        max_betrag=Decimal(g.get("max_betrag", str(d.max_betrag))),
        min_historie=int(g.get("min_historie", d.min_historie)),
        lohn_toleranz_prozent=(None if g.get("lohn_toleranz_prozent", "").strip().lower() == "aus"
                               else Decimal(g.get("lohn_toleranz_prozent", str(d.lohn_toleranz_prozent)))),
        gebuehren_max=Decimal(g.get("gebuehren_max", str(d.gebuehren_max))),
        tage_eindeutig=int(g.get("tage_eindeutig", d.tage_eindeutig)),
        standard_kategorie_ids=frozenset(i.strip() for i in ids.split(",") if i.strip()),
        ausgeschlossen=lade_ausgeschlossen(FEST_PFAD),
        eigene_ibans=frozenset(i.replace(" ", "").upper() for i in
                               config.get("eigene_konten", "ibans", fallback="").split(",") if i.strip()),
        transit_kategorie=config.get("kategorien", "geldtransit", fallback="").strip() or None,
        steuerarten=tuple((k, v.strip()) for k, v in
                          (config["steuerarten"].items() if config.has_section("steuerarten") else [])),
        aliase=tuple((rules.norm(k), rules.norm(a)) for k, v in
                     (config["aliase"].items() if config.has_section("aliase") else [])
                     for a in v.split(",") if a.strip()),
    )


def lade_fest(pfad: Path) -> dict[str, LieferantWissen]:
    if not pfad.exists():
        return {}
    roh = json.loads(pfad.read_text(encoding="utf-8"))
    return {k: LieferantWissen(v["kategorie_id"], v["steuer"], Decimal("0"), fest=True)
            for k, v in roh.items() if not v.get("ausschliessen")}


def lade_ausgeschlossen(pfad: Path) -> frozenset[str]:
    if not pfad.exists():
        return frozenset()
    return frozenset(k for k, v in json.loads(pfad.read_text(encoding="utf-8")).items() if v.get("ausschliessen"))


def speichere_fest(pfad: Path, fest: dict[str, tuple[str, str]]) -> None:
    daten = {k: {"kategorie_id": kat, "steuer": st} for k, (kat, st) in sorted(fest.items())}
    pfad.write_text(json.dumps(daten, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def lade_regeln(pfad: Path) -> list[Standardregel]:
    if not pfad.exists():
        return []
    return [Standardregel(**r) for r in json.loads(pfad.read_text(encoding="utf-8"))]


def speichere_regeln(pfad: Path, regeln: list[Standardregel]) -> None:
    pfad.write_text(json.dumps([asdict(r) for r in regeln], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def verarbeite(faelle: list[Fall], schreiber, conn) -> dict:
    z = {"erledigt": 0, "abgebrochen": 0, "limit": False, "gestoppt": False}
    for f in faelle:
        try:
            schreiber.ausfuehren(f)
            z["erledigt"] += 1
        except actions.Abbruch as e:
            z["abgebrochen"] += 1
            db.review_merken(conn, f.art, _beleg_id(f), f.umsatz.id if f.umsatz else "", str(e), "offen")
            if isinstance(e, actions.AbbruchNachSchreiben):
                z["gestoppt"] = True
                break
        except actions.LimitErreicht:
            z["limit"] = True
            break
    return z


def nur_art(faelle: list[Fall], art: str | None) -> list[Fall]:
    return faelle if art is None else [f for f in faelle if f.art == art]


def nur_umsatz(faelle: list[Fall], umsatz_id: str | None) -> list[Fall]:
    if umsatz_id is None:
        return faelle
    return [f for f in faelle if f.umsatz is not None and f.umsatz.id == umsatz_id]


def _beleg_id(f: Fall) -> str:
    if f.beleg:
        return f.beleg.id
    if f.rechnung:
        return f.rechnung.id
    return f.regel.name if f.regel else ""


def _config() -> configparser.ConfigParser:
    c = configparser.ConfigParser()
    c.read(MODULE_DIR / "config.ini")
    return c


def _einstufen(client, grenzen):
    daten = laden.lade(client)
    wissen = {**rules.lerne(daten.historie, grenzen), **lade_fest(FEST_PFAD)}   # Festgelegtes geht vor
    return daten, rules.einstufen(daten.belege, daten.rechnungen, daten.umsaetze, wissen,
                                  lade_regeln(REGELN_PFAD), grenzen, date.today())


def _zeile(f: Fall) -> str:
    u = f.umsatz
    links = f"{f.datum}  {f.art:<10}"
    if f.beleg:
        links += f"  Beleg {f.beleg.id} {f.beleg.lieferant[:28]:<28} {f.beleg.brutto_eur:>10} {f.beleg.waehrung}"
    elif f.rechnung:
        links += f"  {f.rechnung.nummer} {f.rechnung.kunde[:28]:<28} {f.rechnung.offen:>10}"
    elif f.regel:
        links += f"  Regel {f.regel.name[:34]:<34}"
    if u:
        links += f"  ↔ Umsatz {u.id} {u.betrag:>10} {(u.name or u.zweck)[:30]}"
    if f.korrektur:
        links += f"  Korrektur {f.korrektur}"
    return f"{links}  [{f.grund}]"


def cmd_run(args) -> int:
    grenzen = lade_grenzen(_config())
    client = SevdeskClient(keychain_token(KEYCHAIN_SERVICE))
    _, faelle = _einstufen(client, grenzen)
    sicher = nur_art(nur_umsatz([f for f in faelle if f.sicher], args.umsatz), args.art)
    for f in sicher:
        print(_zeile(f))
    conn = db.connect(MODULE_DIR)
    run_id = db.run_start(conn, args.dry_run)
    schreiber = actions.Schreiber(client, conn, run_id, args.dry_run, args.limit)
    try:
        z = verarbeite(sicher, schreiber, conn)
    except actions.RegelVerletzung as e:
        print(f"STOPP — harte Regel verletzt: {e}")
        return 2
    summe = rules.zusammenfassung(faelle)
    db.run_ende(conn, run_id, {"sicher": z["erledigt"], "review": summe["review"][0], "ohne_beleg": summe["ohne_beleg"][0]})
    modus = "DRY-RUN — nichts geschrieben" if args.dry_run else "geschrieben"
    print(f"\n{modus}: {z['erledigt']} erledigt, {z['abgebrochen']} abgebrochen"
          + (f", Limit {args.limit} erreicht" if z["limit"] else "")
          + (" — GESTOPPT nach Fehler mit Schreibvorgang, Zustand in sevDesk prüfen (status/data.db)" if z["gestoppt"] else ""))
    for k, (n, s) in summe.items():
        print(f"  {k:<20} {n:>5}  {s:>12.2f} €")
    return 0


def cmd_review(args) -> int:
    grenzen = lade_grenzen(_config())
    client = SevdeskClient(keychain_token(KEYCHAIN_SERVICE))
    kat_namen = laden.kategorien(client)
    _, faelle = _einstufen(client, grenzen)
    conn = db.connect(MODULE_DIR)
    abgelehnt = db.abgelehnt(conn)
    offen = [f for f in nur_umsatz(faelle, args.umsatz) if not f.sicher and f.umsatz and f.art in ("beleg", "rechnung", "standard")
             and (f.art, _beleg_id(f), f.umsatz.id) not in abgelehnt]
    run_id = db.run_start(conn, args.dry_run)
    schreiber = actions.Schreiber(client, conn, run_id, args.dry_run, args.limit)
    print(f"{len(offen)} Fälle zur Prüfung. j = übernehmen, n = ablehnen (merken), Enter = überspringen, q = Ende\n")
    for f in offen:
        print(_zeile(f))
        kategorie_id = None
        if f.art == "standard" and f.regel.art == "finanzamt":
            steuer = {i: n for i, n in kat_namen.items() if "steuer" in n.lower()}
            for i, n in sorted(steuer.items(), key=lambda kv: kv[1]):
                print(f"    {i}: {n}")
            kategorie_id = input("  Buchungsart-ID (Enter = überspringen): ").strip() or None
            if kategorie_id is None or kategorie_id not in steuer:
                continue
        antwort = input("  übernehmen? [j/n/Enter/q] ").strip().lower()
        if antwort == "q":
            break
        if antwort == "n":
            db.review_merken(conn, f.art, _beleg_id(f), f.umsatz.id, f.grund, "abgelehnt")
        elif antwort == "j":
            try:
                schreiber.ausfuehren(f, kategorie_id)
                db.review_merken(conn, f.art, _beleg_id(f), f.umsatz.id, f.grund, "angenommen")
                print("  ok")
            except actions.AbbruchNachSchreiben as e:
                print(f"  GESTOPPT nach Schreibvorgang: {e} — Zustand in sevDesk prüfen")
                break
            except actions.Abbruch as e:
                print(f"  abgebrochen: {e}")
            except actions.LimitErreicht:
                print("  Limit erreicht.")
                break
    return 0


def cmd_aufraeumen(args) -> int:
    """Geht echte Duplikate (gleiche Belegnummer) und unplausible Belegdaten durch. Löscht nur nach 'j'."""
    client = SevdeskClient(keychain_token(KEYCHAIN_SERVICE))
    daten = laden.lade(client)
    heute = date.today()
    conn = db.connect(MODULE_DIR)
    schreiber = actions.Schreiber(client, conn, db.run_start(conn, args.dry_run), args.dry_run, 0)
    gruppen = [(b, l) for b, l in (rules.loeschkandidaten(g) for g in rules.echte_duplikate(daten.belege, heute)) if b]
    print(f"{len(gruppen)} Duplikat-Gruppen. j = Duplikate löschen, Enter = überspringen, q = Ende\n")
    for behalten, loeschen in gruppen:
        print(f"{behalten.datum}  {behalten.lieferant[:30]}  {behalten.brutto_eur} {behalten.waehrung}  Nr {behalten.belegnr}")
        print(f"   behalten: {behalten.id}   löschen: {', '.join(b.id for b in loeschen)}")
        antwort = input("   löschen? [j/Enter/q] ").strip().lower()
        if antwort == "q":
            break
        if antwort == "j":
            try:
                for b in loeschen:
                    schreiber.loesche_duplikat(b, behalten)
                print("   gelöscht" if not args.dry_run else "   (dry-run)")
            except actions.Abbruch as e:
                print(f"   STOPP: {e}")
                return 1
    unplausibel = [b for b in daten.belege if b.datum is None or b.datum > heute]
    if unplausibel:
        print(f"\n{len(unplausibel)} Belege mit fehlendem/zukünftigem Datum — in sevDesk korrigieren:")
        for b in unplausibel:
            print(f"   {b.id}  {b.datum}  {b.lieferant[:30]}  {b.brutto_eur} {b.waehrung}  Nr {b.belegnr}")
    return 0


def cmd_usd_auf_eur(args) -> int:
    client = SevdeskClient(keychain_token(KEYCHAIN_SERVICE))
    v = client.get(f"Voucher/{args.beleg}")["objects"][0]
    pos = [laden.parse_position(p) for p in client.get(
        "VoucherPos", params={"voucher[id]": args.beleg, "voucher[objectName]": "Voucher"})["objects"]]
    beleg = laden.parse_beleg(v, pos)
    t = client.get(f"CheckAccountTransaction/{args.umsatz}")["objects"][0]
    if str(t["status"]) != "100":
        print(f"Umsatz {args.umsatz} ist schon zugeordnet (Status {t['status']}).")
        return 1
    umsatz = laden.parse_umsatz(t)
    print(f"Beleg  {beleg.id}  {beleg.datum}  {beleg.lieferant}  {beleg.brutto_fremd} {beleg.waehrung} = {beleg.brutto_eur} EUR"
          f"  Status {beleg.status}  Nr {beleg.belegnr}")
    print(f"Umsatz {umsatz.id}  {umsatz.datum}  {umsatz.betrag} EUR  {(umsatz.name or umsatz.zweck)[:40]}")
    print(f"Neu: Beleg in EUR mit {-umsatz.betrag} EUR, dann Zuordnung.")
    if input("Umstellen und zuordnen? [j/N] ").strip().lower() != "j":
        return 0
    conn = db.connect(MODULE_DIR)
    schreiber = actions.Schreiber(client, conn, db.run_start(conn, args.dry_run), args.dry_run, 1)
    try:
        schreiber.usd_auf_eur(beleg, umsatz)
    except (actions.Abbruch, actions.RegelVerletzung) as e:
        print(f"STOPP: {e}")
        return 1
    print("ok" if not args.dry_run else "(dry-run, nichts geschrieben)")
    return 0


def cmd_gmi_suche(args) -> int:
    """Zahlungen ohne Beleg in GetMyInvoices suchen (nur lesend). Bericht: gmi_bericht.csv (gitignored)."""
    import csv
    from collections import Counter
    from shared.gmi_client import GmiClient
    import gmi
    config = _config()
    grenzen = lade_grenzen(config)
    sevdesk = SevdeskClient(keychain_token(KEYCHAIN_SERVICE))
    daten, faelle = _einstufen(sevdesk, grenzen)
    ohne = [f.umsatz for f in faelle if f.art == "ohne_beleg" and f.umsatz.betrag < 0]
    nummern = {b.belegnr for b in daten.belege + daten.historie if b.belegnr}
    client = GmiClient(keychain_token("ww-gf-cockpit-getmyinvoices"), config.get("getmyinvoices", "konto", fallback=""))
    docs = [gmi.parse_dok(d) for d in client.dokumente("2024-11-01") if d.get("documentType") in gmi.BELEG_TYPEN]
    erg = gmi.einstufen(ohne, docs, nummern, grenzen)
    pfad = MODULE_DIR / "gmi_bericht.csv"
    with pfad.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["status", "datum", "betrag", "empfaenger", "zweck", "umsatz_id", "gmi_uid", "gmi_firma", "gmi_nr", "gmi_datum", "gmi_brutto", "gmi_waehrung"])
        for e in erg:
            d = e.dok
            w.writerow([e.status, e.umsatz.datum, e.umsatz.betrag, e.umsatz.name, e.umsatz.zweck[:80], e.umsatz.id,
                        d.uid if d else "", d.firma if d else "", d.nr if d else "", d.datum if d else "",
                        d.brutto if d else "", d.waehrung if d else ""])
    print(f"{len(docs)} GetMyInvoices-Dokumente, {len(ohne)} Zahlungen ohne Beleg geprüft\n")
    for status in ("nur_gmi", "in_sevdesk", "mehrdeutig", "nicht_gefunden"):
        xs = [e for e in erg if e.status == status]
        print(f"  {status:<15} {len(xs):>5}  {sum(-e.umsatz.betrag for e in xs):>12.2f} €")
    top = Counter(rules.norm(e.umsatz.name) or rules.norm(e.umsatz.zweck)[:30] for e in erg if e.status == "nicht_gefunden")
    print("\nNicht gefunden — häufigste Empfänger:")
    for k, n in top.most_common(15):
        print(f"  {n:>4}  {k}")
    print(f"\nBericht: {pfad.name}")
    return 0


def cmd_status(args) -> int:
    conn = db.connect(MODULE_DIR)
    for r in db.letzte_runs(conn):
        print(f"{r['start']}  {'dry' if r['dry_run'] else 'live'}  erledigt={r['erledigt']} "
              f"review={r['review']} ohne_beleg={r['ohne_beleg']}")
    return 0


def cmd_init_regeln(args) -> int:
    if REGELN_PFAD.exists() and not args.force:
        print(f"{REGELN_PFAD.name} existiert schon. Mit --force überschreiben.")
        return 1
    grenzen = lade_grenzen(_config())
    client = SevdeskClient(keychain_token(KEYCHAIN_SERVICE))
    daten = laden.lade(client)
    regeln = rules.baue_standardregeln(daten.historie, laden.kategorien(client), grenzen)
    speichere_regeln(REGELN_PFAD, regeln)
    print(f"{len(regeln)} Regeln nach {REGELN_PFAD.name} geschrieben. Bitte prüfen.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="sevDesk Belege prüfen, korrigieren, zuordnen")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("run", "review"):
        p = sub.add_parser(name)
        p.add_argument("--dry-run", action="store_true")
        p.add_argument("--limit", type=int, default=20)
        p.add_argument("--umsatz", help="nur den Fall mit dieser Umsatz-ID bearbeiten")
        p.add_argument("--art", choices=("beleg", "rechnung", "standard"), help="nur diese Fallart")
    sub.add_parser("status")
    sub.add_parser("gmi-suche")
    p = sub.add_parser("usd-auf-eur")
    p.add_argument("--beleg", required=True)
    p.add_argument("--umsatz", required=True)
    p.add_argument("--dry-run", action="store_true")
    p = sub.add_parser("aufraeumen")
    p.add_argument("--dry-run", action="store_true")
    p = sub.add_parser("init-regeln")
    p.add_argument("--force", action="store_true")
    args = parser.parse_args()
    handlers = {"run": cmd_run, "review": cmd_review, "status": cmd_status, "init-regeln": cmd_init_regeln,
                "aufraeumen": cmd_aufraeumen, "usd-auf-eur": cmd_usd_auf_eur,
                "gmi-suche": cmd_gmi_suche}
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
