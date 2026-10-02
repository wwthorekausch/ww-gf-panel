# sevdesk-belege

Belegentwürfe (GetMyInvoices) prüfen/korrigieren und Zahlungen zuordnen, Zahlungseingänge auf Ausgangsrechnungen buchen, Umsätze ohne Dokument per Standardbuchung erledigen. Spec: `../docs/superpowers/specs/2026-10-01-sevdesk-belege-design.md`.

## Setup

1. Token: `security add-generic-password -s ww-gf-cockpit-sevdesk -a sevdesk -w`
2. `cp config.ini.example config.ini` (nur Grenzwerte)
3. `python3 -m pip install -r ../requirements.txt` (gemeinsam für alle Module)
4. `python3 cli.py init-regeln` → `standardbuchungen.json` prüfen/anpassen (gitignored, enthält Namen)

## Befehle

    python3 cli.py run --dry-run          # Vorschau, schreibt nichts
    python3 cli.py run --limit 1          # echter Lauf, max. 1 Buchung
    python3 cli.py review [--dry-run]     # unsichere Fälle einzeln entscheiden
    python3 cli.py status                 # letzte Läufe
    python3 cli.py usd-auf-eur --beleg ID --umsatz ID [--dry-run]  # USD-Beleg auf EUR = Bankbetrag, nach "j"
    python3 cli.py gmi-suche               # Zahlungen ohne Beleg in GetMyInvoices suchen (nur lesend) -> gmi_bericht.csv
    python3 cli.py gmi-hochladen [--dry-run] [--limit N] [--umsatz ID]  # PDF aus GMI -> sevDesk-Beleg, zuordnen, GMI-Tag "Sevdesk"
    python3 cli.py gmi-taggen [--dry-run]  # in sevDesk fehlende GMI-Dokumente mit Tag "Sevdesk" markieren (PDF-Download manuell)
    python3 cli.py aufraeumen [--dry-run] # echte Duplikate (gleiche Belegnr) löschen nach "j", unplausible Daten listen
    python3 cli.py init-regeln [--force]  # Standardbuchungen aus Historie ab 2025 erzeugen

Auch über Root: `python3 cockpit.py sevdesk-belege <befehl>`.

`lieferanten.json` (gitignored): von Hand festgelegte Kategorie+Steuer je Lieferant ohne Historie, geht vor Gelerntem.

## Architektur

- `modell.py` Datenklassen · `rules.py` reine Logik · `laden.py` nur GET · `actions.py` alle Schreibzugriffe + Guards · `db.py` Protokoll/Review (SQLite `data.db`) · `cli.py`
- Harte Regeln: Root-`CLAUDE.md` → „Harte Regeln sevDesk“. Erlaubte Schreibpfade nur in `actions.ERLAUBT`.

## Tests

    python3 -m pytest -q

Fixtures nur mit erfundenen Namen/Beträgen/IDs.

## Selflearning

### Lessons

- USD-Belege: `saveVoucher` liest Positions-`sumGross` als Fremdwährung, `propertyExchangeRate` wird ignoriert → Beleg verfälscht (Live 2026-10-01, Beleg manuell repariert). Lösung (bestätigt live 2026-10-01): USD-Beleg per saveVoucher auf `currency: EUR` mit Positions-sumGross = Bankbetrag umstellen, dann bookAmount.

- `bookAmount`: `amount` mit Vorzeichen des Umsatzes (Ausgabe negativ). Positiv bei Ausgabe → Beleg Status 750, paidAmount negativ (Live-Lauf 2026-10-01).
