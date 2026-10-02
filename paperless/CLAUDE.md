# paperless

Duplikat-Prüfung und -Löschung in Paperless-ngx.

## Setup

1. Token: `security add-generic-password -s ww-gf-cockpit-paperless -a paperless -w`
2. `cp config.ini.example config.ini`, URL eintragen (gitignored)

## Befehle

    python3 cli.py duplikate              # nur lesen: Gruppen inhaltsgleicher Dokumente
    python3 cli.py loeschen [--dry-run]   # je Gruppe nach "j": jüngere löschen, ältestes bleibt

## Regeln

- Duplikat = gleicher OCR-Text (Leerraum/Groß-Klein normalisiert, ≥ 50 Zeichen). Ohne OCR-Text nie Duplikat.
- Ältestes (`added`) bleibt. Vor jedem Löschen werden Original und Duplikat frisch geladen und erneut verglichen.
- Jede Löschung → `loeschprotokoll.csv` (gitignored). Paperless legt Gelöschtes in den Papierkorb (wiederherstellbar bis Leerung).

## Tests

    python3 -m pytest -q

## Selflearning

### Lessons
