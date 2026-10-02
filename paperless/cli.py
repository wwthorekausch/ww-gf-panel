#!/usr/bin/env python3
"""Paperless-Duplikate: duplikate (nur lesen), loeschen (nach 'j', ältestes bleibt). Token: Keychain ww-gf-cockpit-paperless."""
import argparse
import configparser
import csv
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from shared.keychain import keychain_token
from shared.paperless_client import PaperlessClient

import regeln

MODULE_DIR = Path(__file__).parent
PROTOKOLL = MODULE_DIR / "loeschprotokoll.csv"


def client() -> PaperlessClient:
    c = configparser.ConfigParser()
    c.read(MODULE_DIR / "config.ini")
    url = c.get("paperless", "url", fallback="")
    if not url:
        raise SystemExit("paperless/config.ini: [paperless] url fehlt (siehe config.ini.example)")
    return PaperlessClient(keychain_token("ww-gf-cockpit-paperless"), url)


def _zeile(d: dict) -> str:
    return f"#{d['id']:<6} {str(d.get('created') or '')[:10]}  {(d.get('title') or '')[:45]:<45}  {(d.get('original_file_name') or '')[:35]}"


def cmd_duplikate(args) -> int:
    docs = client().dokumente()
    gruppen = regeln.gruppen(docs)
    print(f"{len(docs)} Dokumente, {len(gruppen)} Duplikat-Gruppen, {sum(len(g) - 1 for g in gruppen)} löschbar\n")
    for g in gruppen:
        behalten, loeschen = regeln.loeschplan(g)
        print(f"behalten  {_zeile(behalten)}")
        for d in loeschen:
            print(f"löschen   {_zeile(d)}")
        print()
    return 0


def cmd_loeschen(args) -> int:
    c = client()
    gruppen = regeln.gruppen(c.dokumente())
    print(f"{len(gruppen)} Duplikat-Gruppen. j = löschen, Enter = überspringen, q = Ende\n")
    neu = not PROTOKOLL.exists()
    with PROTOKOLL.open("a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, delimiter=";")
        if neu:
            w.writerow(["zeit", "geloescht_id", "behalten_id", "titel", "datei", "dry_run"])
        for g in gruppen:
            behalten, loeschen = regeln.loeschplan(g)
            print(f"behalten  {_zeile(behalten)}")
            for d in loeschen:
                print(f"löschen   {_zeile(d)}")
            antwort = input("  löschen? [j/Enter/q] ").strip().lower()
            if antwort == "q":
                break
            if antwort != "j":
                continue
            frisch_behalten = c.dokument(behalten["id"])          # Original muss noch da und unverändert sein
            for d in loeschen:
                frisch = c.dokument(d["id"])
                if d["id"] == behalten["id"] or not regeln.noch_gleich(frisch_behalten, frisch):
                    print(f"  übersprungen #{d['id']}: nicht mehr inhaltsgleich mit #{behalten['id']}")
                    continue
                if not args.dry_run:
                    c.loeschen(d["id"])
                w.writerow([datetime.now().isoformat(timespec="seconds"), d["id"], behalten["id"],
                            d.get("title"), d.get("original_file_name"), int(args.dry_run)])
                print(f"  {'(dry-run) ' if args.dry_run else ''}gelöscht #{d['id']}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Paperless-Duplikate finden und löschen")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("duplikate")
    l = sub.add_parser("loeschen")
    l.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    return {"duplikate": cmd_duplikate, "loeschen": cmd_loeschen}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
