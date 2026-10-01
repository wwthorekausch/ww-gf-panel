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
python cli.py mahnungen   # Übersicht: Rechnung, Kunde, Betrag, Tage überfällig, Mahnstufe
python cli.py hide <id>   # Rechnung ausblenden: lokales Flag + Tag "nicht-relevant" in sevDesk setzen
python cli.py unhide <id> # Ausblenden rückgängig
```

Auch aufrufbar über zentralen Dispatcher im Root: `python ../cockpit.py sevdesk-mahnwesen <befehl>`

## Architektur

- `sevdesk_client.py` — API-Wrapper (REST, Token-Auth, Basis-URL `https://my.sevdesk.de/api/v1`)
- `db.py` — SQLite-Schema (`data.db`) und Queries
- `mahnwesen.py` — Mahnstufen-Berechnung (Tage überfällig → Stufe, Schwellen aus config.ini)
- `cli.py` — Orchestrierung der Subcommands

## Datenmodell (SQLite: invoices)

id, kunde, betrag, faelligkeitsdatum, status, hidden (0/1), zuletzt_gesehen

## Selflearning

### Lessons
