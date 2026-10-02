#!/usr/bin/env python3
"""Zentraler Einstieg.

    python3 cockpit.py                    # Job-Menü
    python3 cockpit.py job <name|nr>      # Job direkt (z.B. für launchd)
    python3 cockpit.py <modul> <befehl>   # beliebiger Modul-Befehl (wie bisher)
"""
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).parent


@dataclass(frozen=True)
class Job:
    name: str
    beschreibung: str
    modul: str
    argumente: tuple[str, ...]
    schreibt: bool = False


JOBS = [
    Job("sevdesk-vorschau", "sevDesk: Belege/Zahlungen abgleichen — nur Vorschau", "sevdesk-belege", ("run", "--dry-run", "--limit", "1000")),
    Job("sevdesk-buchen", "sevDesk: sichere Fälle buchen (max. 200)", "sevdesk-belege", ("run", "--limit", "200"), True),
    Job("sevdesk-review", "sevDesk: unsichere Fälle einzeln entscheiden", "sevdesk-belege", ("review",), True),
    Job("sevdesk-duplikate", "sevDesk: Beleg-Duplikate löschen (nach j)", "sevdesk-belege", ("aufraeumen",), True),
    Job("sevdesk-status", "sevDesk: letzte Läufe", "sevdesk-belege", ("status",)),
    Job("mahnungen", "Mahnwesen: überfällige Rechnungen (frisch aus sevDesk)", "sevdesk-mahnwesen", ("mahnungen", "--sync")),
    Job("offene-posten", "Mahnwesen: offener Betrag pro Kunde (frisch aus sevDesk)", "sevdesk-mahnwesen", ("offen", "--sync")),
    Job("gmi-suche", "GetMyInvoices: Zahlungen ohne Beleg suchen (Bericht)", "sevdesk-belege", ("gmi-suche",)),
    Job("gmi-taggen", "GetMyInvoices: in sevDesk fehlende Belege mit Tag 'Sevdesk'", "sevdesk-belege", ("gmi-taggen",), True),
    Job("paperless-duplikate", "Paperless: Duplikate anzeigen", "paperless", ("duplikate",)),
    Job("paperless-duplikate-loeschen", "Paperless: Duplikate löschen (nach j)", "paperless", ("loeschen",), True),
    Job("paperless-vorschau", "Paperless: Felder ergänzen — nur Vorschau", "paperless", ("anreichern", "--dry-run")),
    Job("paperless-anreichern", "Paperless: leere Felder/Korrespondent/Speicherpfad ergänzen", "paperless", ("anreichern",), True),
    Job("paperless-korrigieren", "Paperless: falsche Werte/Korrespondenten korrigieren (nach j)", "paperless", ("korrigieren",), True),
]


def finde_job(wahl: str) -> Job | None:
    if wahl.isdigit() and 1 <= int(wahl) <= len(JOBS):
        return JOBS[int(wahl) - 1]
    return next((j for j in JOBS if j.name == wahl), None)


def starte(job: Job, nachfragen: bool = True) -> int:
    if job.schreibt and nachfragen:
        if input(f"'{job.beschreibung}' schreibt in externe Systeme. Starten? [j/N] ").strip().lower() != "j":
            return 0
    return subprocess.call([sys.executable, str(ROOT / job.modul / "cli.py"), *job.argumente], cwd=ROOT / job.modul)


def menue() -> int:
    for i, j in enumerate(JOBS, 1):
        print(f"{i:>2}  {'✎' if j.schreibt else ' '}  {j.name:<30} {j.beschreibung}")
    print("\n✎ = schreibt (mit Rückfrage).  q = Ende")
    wahl = input("Job: ").strip()
    if wahl in ("", "q"):
        return 0
    job = finde_job(wahl)
    if job is None:
        print(f"Unbekannter Job '{wahl}'")
        return 1
    return starte(job)


def main() -> int:
    if len(sys.argv) == 1:
        return menue()
    if sys.argv[1] == "job":
        job = finde_job(sys.argv[2]) if len(sys.argv) > 2 else None
        if job is None:
            print("Nutzung: python3 cockpit.py job <name|nr>  —  Jobs:", ", ".join(j.name for j in JOBS))
            return 1
        return starte(job, nachfragen="--ja" not in sys.argv)
    module_cli = ROOT / sys.argv[1] / "cli.py"
    if not module_cli.exists():
        print(f"Modul '{sys.argv[1]}' nicht gefunden (erwartet: {module_cli})")
        return 1
    return subprocess.call([sys.executable, str(module_cli), *sys.argv[2:]], cwd=module_cli.parent)


if __name__ == "__main__":
    sys.exit(main())
