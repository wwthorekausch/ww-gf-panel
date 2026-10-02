# sevdesk-mahnwesen

Übersicht offener Rechnungen aus sevDesk mit lokal berechneten Mahnstufen. Ausblenden nicht relevanter Rechnungen (lokal + Tag in sevDesk).

## Setup

1. API-Token in macOS Keychain: `security add-generic-password -s ww-gf-cockpit-sevdesk -a sevdesk -w`
   `config.ini` in diesem Ordner anlegen (gitignored, keine Secrets):
   ```ini
   [mahnstufen]
   stufe_1_tage = 7
   stufe_2_tage = 14
   stufe_3_tage = 30
   ```
2. `pip install -r requirements.txt`

## Befehle

```bash
python cli.py sync        # offene Rechnungen von sevDesk holen, lokale DB aktualisieren
python cli.py mahnungen [--sync]  # ab 01.01.2025: Handlungsbedarf laut sevDesk — Stufe = dunningLevel, Frist = reminderDeadline der letzten Mahnung (sonst Datum + Zahlungsziel), Entwurf → versenden
python cli.py offen [--sync]      # offener Betrag pro Kunde, davon überfällig (Gutschriften gegengerechnet)
python cli.py hide <id>   # Rechnung ausblenden: lokales Flag + Tag "nicht-relevant" in sevDesk setzen
python cli.py unhide <id> # Ausblenden rückgängig
```

Auch aufrufbar über zentralen Dispatcher im Root: `python ../cockpit.py sevdesk-mahnwesen <befehl>`

python cli.py mahnung-entwurf <RE-nr> [--dry-run]  # Mahnungs-Entwurf (MA) anlegen, nur wenn laut Liste fällig; versendet nichts

python cli.py mahnung-senden <RE-nr> [--an mail] [--dry-run]  # Entwurf per E-Mail (PDF) senden, nach Vorschau + j

## Absprachen

`mahn_absprachen.json` (gitignored, Vorlage `mahn_absprachen.example.json`): Kunden (Teilstring ohne Sonderzeichen, optional `rechnung`) mit `aktion` `nicht_mahnen` oder `inkasso` + `notiz`. `mahnungen` nimmt sie aus den Mahnstufen und listet sie separat unter „Absprachen“.

## Architektur

- `sevdesk_client.py` — API-Wrapper (REST, Token-Auth, Basis-URL `https://my.sevdesk.de/api/v1`)
- `db.py` — SQLite-Schema (`data.db`) und Queries
- `mahnwesen.py` — Mahnstufen-Berechnung (Tage überfällig → Stufe, Schwellen aus config.ini)
- `cli.py` — Orchestrierung der Subcommands

## Datenmodell (SQLite: invoices)

id, kunde, betrag, faelligkeitsdatum, status, hidden (0/1), zuletzt_gesehen

## Selflearning

### Lessons
