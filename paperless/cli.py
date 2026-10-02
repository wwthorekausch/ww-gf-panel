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

import anreichern
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


def _quellen():
    """sevDesk-Rechnungen/-Belege (alle Status) und GMI-Dokumente als einfache Dicts (nur lesend)."""
    from decimal import Decimal
    from shared.gmi_client import GmiClient
    from shared.sevdesk_client import SevdeskClient
    sys.path.insert(0, str(MODULE_DIR.parent / "sevdesk-belege"))
    import laden
    d = lambda x: Decimal(str(x)) if x not in (None, "") else None
    sev = SevdeskClient(keychain_token("ww-gf-cockpit-sevdesk"))
    rechnungen = {}
    for r in laden.alle(sev, "Invoice", {"embed": "contact"}):
        kontakt = r.get("contact") or {}
        rechnungen[r.get("invoiceNumber") or ""] = anreichern.Quelle(
            nummer=r.get("invoiceNumber"), brutto=d(r.get("sumGross")), netto=d(r.get("sumNet")),
            firma=kontakt.get("name") or r.get("addressName"), kundennummer=kontakt.get("customerNumber"),
            sevdesk_id=str(r["id"]), rechnungstyp=anreichern.RECHNUNGSTYP.get(r.get("invoiceType") or ""))
    belege = [{"id": str(v["id"]), "nr": (v.get("description") or "").strip(), "status": v.get("status"),
               "firma": v.get("supplierName") or (v.get("supplier") or {}).get("name"),
               "brutto": d(v.get("sumGross")), "netto": d(v.get("sumNet"))}
              for v in laden.alle(sev, "Voucher", {"embed": "supplier"})]
    cfg = configparser.ConfigParser()
    cfg.read(MODULE_DIR.parent / "sevdesk-belege" / "config.ini")
    gmi = GmiClient(keychain_token("ww-gf-cockpit-getmyinvoices"), cfg.get("getmyinvoices", "konto", fallback=""))
    gmi_docs = [{"id": f"GMI-{g['documentUid']}", "nr": (g.get("documentNumber") or "").strip(), "firma": g.get("companyName"),
                 "brutto": d(g.get("grossAmount")), "netto": d(g.get("netAmount")), "zahlart": g.get("paymentMethod"),
                 "typ": g.get("documentType")} for g in gmi.dokumente("2024-01-01")]
    return rechnungen, belege, gmi_docs


def cmd_anreichern(args) -> int:
    c = client()
    cf = {f["name"]: f["id"] for f in c.alle("custom_fields")}
    optionen = {}
    for f in c.alle("custom_fields"):
        if f["data_type"] == "select":
            optionen[f["name"]] = {o["label"]: o["id"] for o in (f.get("extra_data") or {}).get("select_options", [])}
    typen = {t["name"]: t["id"] for t in c.alle("document_types")}
    pfad = next((p["id"] for p in c.alle("storage_paths") if p["name"] == "Belege"), None)
    korrespondenten = c.alle("correspondents")
    rechnungen, belege, gmi_docs = _quellen()
    docs = c.dokumente()
    patches, fehlt, neue_korr = [], [], set()
    for doc in docs:
        quelle, status = None, ""
        if doc.get("document_type") == typen.get("Ausgangsrechnung"):
            nr = anreichern.re_nummer(doc)
            quelle = rechnungen.get(nr or "")
            status = "" if quelle else f"Ausgangsrechnung {nr or '(Nr. nicht eindeutig)'} nicht in sevDesk"
        elif doc.get("document_type") == typen.get("Eingangsrechnung"):
            sb, gb = anreichern.finde_beleg(doc, belege), anreichern.finde_beleg(doc, gmi_docs)
            if sb or gb:
                basis = sb or gb
                quelle = anreichern.Quelle(nummer=basis["nr"], brutto=basis["brutto"], netto=basis["netto"], firma=basis["firma"],
                                           sevdesk_id=sb["id"] if sb else None,
                                           rechnungstyp="Gutschrift" if (gb or {}).get("typ") == "CREDIT_NOTE" else "Rechnung",
                                           zahlart=anreichern.zahlart((gb or {}).get("zahlart")))
            if not sb:
                status = "Eingangsrechnung nicht in sevDesk" + (f" (in GMI: {gb['nr']})" if gb else " (auch nicht in GMI)")
        if status:
            fehlt.append((doc, status))
        kid, neu_name = None, None
        if quelle and anreichern.korrespondent_tauglich(quelle.firma):
            kid = anreichern.korrespondent_id(quelle.firma, korrespondenten)
            if kid is None and not doc.get("correspondent"):
                neue_korr.add(quelle.firma)
                neu_name = quelle.firma          # wird erst beim Schreiben dieses Dokuments angelegt
        body = anreichern.plan(doc, quelle, cf, optionen, kid, pfad)
        if body or neu_name:
            patches.append((doc, body or {}, neu_name))
    with (MODULE_DIR / "fehlt_in_sevdesk.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["paperless_id", "titel", "datei", "datum", "status"])
        for doc, status in fehlt:
            w.writerow([doc["id"], doc.get("title"), doc.get("original_file_name"), doc.get("created"), status])
    felder = {}
    for _, b, _n in patches:
        for k in b:
            felder[k] = felder.get(k, 0) + 1
    print(f"{len(docs)} Dokumente: {len(patches)} zu ergänzen {felder}, {len(neue_korr)} neue Korrespondenten, "
          f"{len(fehlt)} fehlen in sevDesk (fehlt_in_sevdesk.csv)")
    if args.dry_run:
        for doc, b, neu in patches[:8]:
            print(f"  #{doc['id']:<5} {(doc.get('title') or '')[:40]:<40} {b}{' + neuer Korrespondent ' + neu if neu else ''}")
        print(f"  neue Korrespondenten: {sorted(neue_korr)[:15]}")
        return 0
    geschrieben = []
    for doc, b, neu in patches[: args.limit]:
        if neu:
            kid = anreichern.korrespondent_id(neu, korrespondenten)
            if kid is None:
                k = c.korrespondent_anlegen(neu)
                korrespondenten.append(k)
                kid = k["id"]
            b = {**b, "correspondent": kid}
        c.dokument_patchen(doc["id"], b)
        geschrieben.append(str(doc["id"]))
    (MODULE_DIR / "anreichern_letzter_lauf.txt").write_text(" ".join(geschrieben), encoding="utf-8")
    print(f"geschrieben: {len(geschrieben)} Dokumente (IDs in anreichern_letzter_lauf.txt)")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Paperless-Duplikate finden und löschen")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("duplikate")
    l = sub.add_parser("loeschen")
    l.add_argument("--dry-run", action="store_true")
    a = sub.add_parser("anreichern")
    a.add_argument("--dry-run", action="store_true")
    a.add_argument("--limit", type=int, default=1000)
    args = p.parse_args()
    return {"duplikate": cmd_duplikate, "loeschen": cmd_loeschen, "anreichern": cmd_anreichern}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
