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
- [sevdesk-belege](sevdesk-belege/CLAUDE.md) — Belege prüfen/korrigieren, Zahlungen zuordnen, Standardbuchungen (sevDesk API)
- [paperless](paperless/CLAUDE.md) — Paperless-Duplikate finden und löschen
- [launchd](launchd/CLAUDE.md) — täglicher Lauf 07:00 (nur Jobs ohne Rückfrage)
- [n8n](n8n/CLAUDE.md) — n8n-Import-Workflows (Gmail GMI-Label → Paperless; Paperless-Rechnungen mit Gemini prüfen)
- [bwa](bwa/CLAUDE.md) — monatliche BWA-Daten (JSON) + Auswertungen zum Monatsvergleich

## Zentrale Ausführung

```bash
python cockpit.py <modul> <befehl> [args...]
# Beispiel:
python cockpit.py sevdesk-mahnwesen sync
python cockpit.py sevdesk-mahnwesen mahnungen
```

`python3 cockpit.py` ohne Argumente = Job-Menü (Liste `JOBS` in `cockpit.py`, schreibende Jobs mit Rückfrage); `cockpit.py job <name>` startet direkt. `cockpit.py` sucht im angegebenen Modul-Ordner nach `cli.py` und leitet Befehl+Argumente weiter. Neues Modul hinzufügen = neuer Unterordner mit eigener `cli.py` und `CLAUDE.md`, kein Änderung an `cockpit.py` nötig.

## Config / Secrets

Jedes Modul verwaltet eigene `config.ini` innerhalb seines Ordners (gitignored, enthält Tokens). Kein zentrales Secret-File — Trennung pro Modul.

## Repo

`git@github.com:wwthorekausch/ww-gf-panel.git` — nur Tooling. Daten, Ergebnisse, PDFs, `config.ini`, `*.db`, `TODO.md`, generierte `standardbuchungen.json` sind per `.gitignore` ausgeschlossen. Testdaten/Fixtures immer anonymisiert (keine echten Namen, Beträge, IDs). Vor jedem Push `git diff --cached --name-only` prüfen.

## Harte Regeln Paperless

- Löschen nur inhaltsgleicher Duplikate über `paperless loeschen` nach Einzel-Freigabe „j“; ältestes bleibt; Token nur aus Keychain `ww-gf-cockpit-paperless`.

## Harte Regeln sevDesk

- Rechnungen, Gutschriften und Stornorechnungen (Ausgangsbelege) nie direkt im Status ändern (kein manuelles bezahlt/storniert/Entwurf, kein Löschen, keine Inhaltsänderung). Erlaubt: Zahlung zuordnen (`bookAmount`) — dass sevDesk dadurch selbst auf bezahlt setzt, ist ok.
- Eingangsbelege (Voucher): Lieferantenname (`supplierName`, nur dieses Feld) nach OCR-Wert aus Paperless setzen, nur über `paperless korrigieren` nach Einzel-Freigabe „j“ (Entscheidung 2026-10-02: OCR-Daten haben Vorrang).
- Mahnungen: Entwürfe anlegen (`Invoice/Factory/createInvoiceReminder`) über `sevdesk-mahnwesen mahnung-entwurf`; Versand per E-Mail (`Invoice/{id}/sendViaEmail`) nur über `mahnung-senden` nach Vorschau (Empfänger + Text) und ausdrücklicher Freigabe je Mahnung. Rechnung selbst bleibt unverändert. Offene Mahngebühren bezahlter Rechnungen nur per `mahngebuehr-erlassen` (bookAmount 0 €, Typ O = Minderung, kein Geldfluss).
- Nur Belege und Umsätze ab 01.01.2025 anfassen, Abarbeitung von neu nach alt.
- GetMyInvoices: Key nur aus Keychain `ww-gf-cockpit-getmyinvoices`. Einziger Schreibzugriff: Tag „Sevdesk“ an Dokument anhängen (vorhandene Tags bleiben), nur über `sevdesk-belege gmi-hochladen`.
- Nie löschen — einzige Ausnahme: Belegentwurf-Duplikate (Status 50, gleiche Belegnummer + Lieferant + Betrag + Datum, ältester bleibt), nur über `sevdesk-belege aufraeumen` nach Einzel-Freigabe „j“ (Entscheidung 2026-10-01).
- sevDesk-Schreibzugriffe nur über Cockpit-Befehle mit Dry-Run-Vorschau; API-Token nur aus macOS Keychain (`security find-generic-password -s ww-gf-cockpit-sevdesk -w`), nie in Dateien.

## Selflearning

Jedes Mal, wenn der Nutzer eine Korrektur gibt oder ich selbst einen Fehler feststelle, wird unter ##Lessons eine Einzeiler-Lektion ergänzt, damit derselbe Fehler künftig nicht wiederholt wird.

### Lessons

- Nur selbst geänderte Dateien gezielt stagen (`git add <pfade>`), nie `git add -A` — sonst landen fremde Änderungen (andere Sitzung/Nutzer) ungeprüft im Commit.

- Befehle für den Nutzer immer ortsunabhängig angeben (Alias `cockpit` oder absoluter Pfad / `cd` davor) — Nutzer startet aus `~`, relative `python3 cli.py` schlagen fehl.
