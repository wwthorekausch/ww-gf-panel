# WW-GF-Cockpit

Lokale Automatisierung für Geschäftsführungs-Aufgaben: sevDesk-Buchhaltung, GetMyInvoices, Paperless, BWA-Auswertung. Jeder Teilbereich liegt in einem eigenen Unterordner mit eigener `CLAUDE.md`.

## Jobs starten

Einmalig globalen Befehl anlegen (fish), dann von jedem Ordner aus nutzbar:

```fish
alias --save cockpit 'python3 "/Users/thorekausch/Documents/workplaces/ww/WW KI Themen/WW-GF-Cockpit/cockpit.py"'
```

Danach `cockpit` (Menü) bzw. `cockpit job <name>`. Ohne Alias: im Projektordner `python3 cockpit.py …`.

```bash
python3 cockpit.py                      # Menü: Nummer eingeben, Enter
python3 cockpit.py job sevdesk-vorschau # Job direkt per Name oder Nummer
python3 cockpit.py job 2 --ja           # ohne Rückfrage (z.B. für Zeitplan)
```

| Nr | Job | Was passiert | schreibt |
|---:|---|---|:---:|
| 1 | `sevdesk-vorschau` | Belege und Zahlungen abgleichen, nur Vorschau | – |
| 2 | `sevdesk-buchen` | sichere Fälle in sevDesk buchen (max. 200 pro Lauf) | ✎ |
| 3 | `sevdesk-review` | unsichere Fälle einzeln entscheiden (j/n) | ✎ |
| 4 | `sevdesk-duplikate` | Beleg-Duplikate (gleiche Belegnummer) löschen nach „j“ | ✎ |
| 5 | `sevdesk-status` | letzte Läufe anzeigen | – |
| – | `mahnungen` | überfällige Rechnungen mit Mahnstufe (lädt frisch, nur lesen) | – |
| – | `offene-posten` | offener Betrag pro Kunde (lädt frisch, nur lesen) | – |
| 6 | `gmi-suche` | Zahlungen ohne Beleg in GetMyInvoices suchen → `gmi_bericht.csv` | – |
| 7 | `gmi-taggen` | in sevDesk fehlende GetMyInvoices-Dokumente mit Tag „Sevdesk“ markieren | ✎ |
| 8 | `paperless-duplikate` | inhaltsgleiche Dokumente anzeigen | – |
| 9 | `paperless-duplikate-loeschen` | Duplikate löschen nach „j“ (ältestes bleibt) | ✎ |
| 10 | `paperless-vorschau` | Felder ergänzen, nur Vorschau + `fehlt_in_sevdesk.csv` | – |
| 11 | `paperless-anreichern` | leere Felder, Korrespondent, Speicherpfad aus sevDesk/GetMyInvoices ergänzen | ✎ |
| 12 | `paperless-korrigieren` | abweichende Werte/Korrespondenten korrigieren nach „j“ | ✎ |

✎-Jobs fragen vor dem Start nach. Empfohlene Reihenfolge: erst Vorschau (1, 10), dann schreibenden Job (2, 11).

Typischer Ablauf:

1. `sevdesk-vorschau` → `sevdesk-buchen`
2. `gmi-suche` → `gmi-taggen` → PDFs in GetMyInvoices über Tag „Sevdesk“ laden und in sevDesk hochladen → wieder `sevdesk-buchen`
3. `paperless-duplikate-loeschen` → `paperless-anreichern` → `paperless-korrigieren`

Jeder Modul-Befehl geht weiterhin direkt: `python3 cockpit.py <modul> <befehl> [args]`, z.B. `python3 cockpit.py sevdesk-belege usd-auf-eur --beleg … --umsatz …`.

## Alfred

`python3 alfred/bauen.py`, dann `alfred/GF-Cockpit.alfredworkflow` doppelklicken. In Alfred `gf <suche>`: Enter startet den Job im Terminal, ⌘+Enter lesende Jobs im Hintergrund mit Mitteilung. Details: [alfred/CLAUDE.md](alfred/CLAUDE.md).

## Testen

Schritt-für-Schritt mit konkreten Befehlen: [TESTPLAN.md](TESTPLAN.md).

## Täglicher Lauf

07:00 automatisch: sichere sevDesk-Buchungen + GetMyInvoices-Bericht, Mitteilung mit Ergebnis. Installation siehe [launchd/CLAUDE.md](launchd/CLAUDE.md).

## Setup

```bash
python3 -m pip install -r sevdesk-belege/requirements.txt
```

Secrets nur in der macOS-Keychain (nie in Dateien):

```bash
security add-generic-password -s ww-gf-cockpit-sevdesk -a sevdesk -w
security add-generic-password -s ww-gf-cockpit-getmyinvoices -a getmyinvoices -w
security add-generic-password -s ww-gf-cockpit-paperless -a paperless -w
```

Lokale Konfiguration (gitignored) aus den Vorlagen anlegen:

- `sevdesk-belege/config.ini` ← `config.ini.example` (Grenzwerte, Aliase, Steuerarten, eigene IBANs, GMI-Konto-ID)
- `paperless/config.ini` ← `config.ini.example` (Paperless-URL)
- `sevdesk-belege/standardbuchungen.json`: `python3 cockpit.py sevdesk-belege init-regeln`

## Module

| Ordner | Inhalt |
|---|---|
| [sevdesk-belege](sevdesk-belege/CLAUDE.md) | Belege prüfen/korrigieren, Zahlungen zuordnen, Standardbuchungen, Umbuchungen, USD→EUR, GetMyInvoices-Abgleich |
| [paperless](paperless/CLAUDE.md) | Duplikate, Felder/Korrespondenten/Speicherpfad anreichern und korrigieren |
| [sevdesk-mahnwesen](sevdesk-mahnwesen/CLAUDE.md) | offene Rechnungen, Mahnstufen |
| [n8n](n8n/CLAUDE.md) | Import-Workflow Gmail (Label GMI) → Paperless |
| [bwa](bwa/CLAUDE.md) | monatliche BWA-Auswertung (Daten lokal) |
| [alfred](alfred/CLAUDE.md) | Alfred-Workflow `gf` zum Starten der Jobs |

## Sicherheit

- Schreibzugriffe nur über festgelegte Pfade mit Dry-Run, Protokoll und Rückfrage; harte Regeln in [CLAUDE.md](CLAUDE.md).
- Daten, Ergebnisse, PDFs, `config.ini`, `*.db`, `*.csv` bleiben lokal (`.gitignore`). Im Repo nur Tooling.

## Tests

```bash
python3 -m pytest tests -q
(cd sevdesk-belege && python3 -m pytest -q)
(cd paperless && python3 -m pytest -q)
```

## Neues Modul / neuer Job

1. Unterordner mit eigener `cli.py` (Subcommands) und `CLAUDE.md`
2. Job in `JOBS` in `cockpit.py` eintragen (Name, Beschreibung, Modul, Argumente, `schreibt`)
3. Zeile in dieser README und in der Root-`CLAUDE.md` ergänzen
