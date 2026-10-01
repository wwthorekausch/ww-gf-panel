# WW-GF-Cockpit

Lokale Skript-Sammlung zur Automatisierung von Geschäftsführungs-Tätigkeiten (z.B. sevDesk). Jeder Teilbereich liegt in eigenem Unterordner mit eigener `CLAUDE.md`.

## Setup

```bash
pip install -r sevdesk-mahnwesen/requirements.txt
```

Modul-Config anlegen: `sevdesk-mahnwesen/config.ini` (siehe [sevdesk-mahnwesen/CLAUDE.md](sevdesk-mahnwesen/CLAUDE.md)).

## Zentrale Ausführung

Alle Befehle laufen über `cockpit.py` im Root:

```bash
python cockpit.py <modul> <befehl> [args...]
```

## Module & Befehle

### sevdesk-mahnwesen

Übersicht offener Rechnungen, Mahnstufen, Ausblenden nicht relevanter Rechnungen.

| Befehl | Funktion |
|---|---|
| `python cockpit.py sevdesk-mahnwesen sync` | Offene Rechnungen von sevDesk holen, lokale DB (`data.db`) aktualisieren |
| `python cockpit.py sevdesk-mahnwesen mahnungen` | Übersicht: Rechnung, Kunde, Betrag, Tage überfällig, Mahnstufe (1/2/3) |
| `python cockpit.py sevdesk-mahnwesen hide <id>` | Rechnung ausblenden (lokales Flag + Tag "nicht-relevant" in sevDesk) |
| `python cockpit.py sevdesk-mahnwesen unhide <id>` | Ausblenden rückgängig |

Mahnstufen-Schwellen (Standard 7/14/30 Tage) in `sevdesk-mahnwesen/config.ini` anpassbar.

## Neues Modul hinzufügen

1. Neuer Unterordner (z.B. `neues-modul/`)
2. Eigene `cli.py` mit Subcommands + eigene `CLAUDE.md`
3. Zeile in diese README und Root-`CLAUDE.md` ergänzen — `cockpit.py` selbst bleibt unverändert
