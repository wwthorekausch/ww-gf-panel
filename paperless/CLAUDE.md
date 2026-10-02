# paperless

Duplikat-Prüfung und -Löschung in Paperless-ngx.

## Setup

1. Token: `security add-generic-password -s ww-gf-cockpit-paperless -a paperless -w`
2. `cp config.ini.example config.ini`, URL eintragen (gitignored)

## Befehle

    python3 cli.py duplikate              # nur lesen: Gruppen inhaltsgleicher Dokumente
    python3 cli.py loeschen [--dry-run]   # je Gruppe nach "j": jüngere löschen, ältestes bleibt
    python3 cli.py anreichern [--dry-run] [--limit N]  # leere Felder/Korrespondent/Speicherpfad aus sevDesk/GMI, fehlt_in_sevdesk.csv
    python3 cli.py korrigieren [--dry-run] # Abweichungen zur Quelle je Dokument nach "j" überschreiben

OCR hat Vorrang: Dokumente mit Tag „KI-geprüft“ (Gemini-Workflow, siehe `n8n/`) werden von `korrigieren` nie aus sevDesk/GMI überschrieben. Weicht deren Firma vom sevDesk-Eingangsbeleg ab, fragt `korrigieren` „sevDesk aktualisieren?“ → nach „j“ `supplierName` am Beleg setzen + nachlesen.

## Regeln

- Duplikat = gleicher OCR-Text (Leerraum/Groß-Klein normalisiert, ≥ 50 Zeichen). Ohne OCR-Text nie Duplikat.
- Ältestes (`added`) bleibt. Vor jedem Löschen werden Original und Duplikat frisch geladen und erneut verglichen.
- Jede Löschung → `loeschprotokoll.csv` (gitignored). Paperless legt Gelöschtes in den Papierkorb (wiederherstellbar bis Leerung).

## Tests

    python3 -m pytest -q

## Selflearning

### Lessons

- Nummer nur im OCR-Text ist schwach (PLZ 24114 = Vicci-Rechnungsnr) → nur mit Betrag im Text zählen. Netto==Brutto aus sevDesk/GMI oft falsch → nur übernehmen, was der Text belegt.
