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
from modell import Fall, Grenzen, Standardregel

MODULE_DIR = Path(__file__).parent
REGELN_PFAD = MODULE_DIR / "standardbuchungen.json"
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
        lohn_toleranz_prozent=Decimal(g.get("lohn_toleranz_prozent", str(d.lohn_toleranz_prozent))),
        gebuehren_max=Decimal(g.get("gebuehren_max", str(d.gebuehren_max))),
        standard_kategorie_ids=frozenset(i.strip() for i in ids.split(",") if i.strip()),
    )


def lade_regeln(pfad: Path) -> list[Standardregel]:
    if not pfad.exists():
        return []
    return [Standardregel(**r) for r in json.loads(pfad.read_text(encoding="utf-8"))]


def speichere_regeln(pfad: Path, regeln: list[Standardregel]) -> None:
    pfad.write_text(json.dumps([asdict(r) for r in regeln], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def verarbeite(faelle: list[Fall], schreiber, conn) -> dict:
    z = {"erledigt": 0, "abgebrochen": 0, "limit": False}
    for f in faelle:
        try:
            schreiber.ausfuehren(f)
            z["erledigt"] += 1
        except actions.Abbruch as e:
            z["abgebrochen"] += 1
            db.review_merken(conn, f.art, _beleg_id(f), f.umsatz.id if f.umsatz else "", str(e), "offen")
        except actions.LimitErreicht:
            z["limit"] = True
            break
    return z


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
    wissen = rules.lerne(daten.historie, grenzen)
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
    sicher = [f for f in faelle if f.sicher]
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
          + (f", Limit {args.limit} erreicht" if z["limit"] else ""))
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
    offen = [f for f in faelle if not f.sicher and f.umsatz and f.art in ("beleg", "rechnung", "standard")
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
            except actions.Abbruch as e:
                print(f"  abgebrochen: {e}")
            except actions.LimitErreicht:
                print("  Limit erreicht.")
                break
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
    sub.add_parser("status")
    p = sub.add_parser("init-regeln")
    p.add_argument("--force", action="store_true")
    args = parser.parse_args()
    handlers = {"run": cmd_run, "review": cmd_review, "status": cmd_status, "init-regeln": cmd_init_regeln}
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
