# WW-GF-Cockpit

Sammlung lokaler Automatisierungs-Skripte für Geschäftsführungs-Tätigkeiten (z.B. sevDesk-Automatisierung). Jeder Teilbereich liegt in eigenem Unterordner mit eigener `CLAUDE.md` (Details, Setup, Befehle dort).

## Struktur

- Jeder Teilbereich = ein Unterordner (z.B. `sevdesk-mahnwesen/`)
- Jeder Unterordner hat eigene `CLAUDE.md` mit Details zum Modul
- Zentrale Ausführung über `cockpit.py` im Root — dispatcht Befehle an das jeweilige Modul

## Gemeinsame Bausteine

`shared/` — wiederverwendbare Elemente für alle Module: `sevdesk_client.py` (REST-Client, Base-URL/Auth laut [sevdesk-mcp](https://github.com/DigitalVereinfacht/sevdesk-mcp)-Referenz), `config.py` (INI-Loader), `db.py` (SQLite-Connection-Helper). Neue Module importieren daraus statt Code zu duplizieren.

## Teilbereiche

- [sevdesk-mahnwesen](sevdesk-mahnwesen/CLAUDE.md) — Übersicht offener Rechnungen, Mahnstufen, Ausblenden nicht relevanter Rechnungen (sevDesk API)
- [bwa](bwa/CLAUDE.md) — monatliche BWA-Daten (JSON) + Auswertungen zum Monatsvergleich

## Zentrale Ausführung

```bash
python cockpit.py <modul> <befehl> [args...]
# Beispiel:
python cockpit.py sevdesk-mahnwesen sync
python cockpit.py sevdesk-mahnwesen mahnungen
```

`cockpit.py` sucht im angegebenen Modul-Ordner nach `cli.py` und leitet Befehl+Argumente weiter. Neues Modul hinzufügen = neuer Unterordner mit eigener `cli.py` und `CLAUDE.md`, kein Änderung an `cockpit.py` nötig.

## Config / Secrets

Jedes Modul verwaltet eigene `config.ini` innerhalb seines Ordners (gitignored, enthält Tokens). Kein zentrales Secret-File — Trennung pro Modul.

## Harte Regeln sevDesk

- Rechnungen, Gutschriften und Stornorechnungen (Ausgangsbelege) nie direkt im Status ändern (kein manuelles bezahlt/storniert/Entwurf, kein Löschen, keine Inhaltsänderung). Erlaubt: Zahlung zuordnen (`bookAmount`) — dass sevDesk dadurch selbst auf bezahlt setzt, ist ok.
- Nur Belege und Umsätze ab 01.01.2025 anfassen, Abarbeitung von neu nach alt.
- sevDesk-Schreibzugriffe nur über Cockpit-Befehle mit Dry-Run-Vorschau; API-Token nur aus macOS Keychain (`security find-generic-password -s ww-gf-cockpit-sevdesk -w`), nie in Dateien.

## Selflearning

Jedes Mal, wenn der Nutzer eine Korrektur gibt oder ich selbst einen Fehler feststelle, wird unter ##Lessons eine Einzeiler-Lektion ergänzt, damit derselbe Fehler künftig nicht wiederholt wird.

### Lessons
