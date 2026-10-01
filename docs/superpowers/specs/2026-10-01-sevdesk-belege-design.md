# sevdesk-belege — Design (Teil A)

Stand: 2026-10-01. Teil B (fehlende Belege via GetMyInvoices beschaffen) folgt als eigene Spec und baut auf der Liste „Zahlung ohne Beleg“ aus Teil A auf.

## Ziel

Zu jeder Zahlung ab 01.01.2025 gibt es in sevDesk einen zugeordneten Beleg. sevDesk ist Quelle für den DATEV-Export an den Steuerberater — was hier sauber ist, kommt sauber in der BWA an.

Erfolg:
- Belegentwürfe aus GetMyInvoices werden geprüft, korrigiert und ihrer Zahlung zugeordnet.
- Zahlungseingänge werden offenen Ausgangsrechnungen zugeordnet.
- Umsätze ohne Dokument (Lohn, Krankenkasse, Finanzamt, Bankgebühren) bekommen ihre Standardbuchung.
- Was nicht sicher ist, landet in einer Review-Liste. Was keinen Beleg findet, landet in der Liste „Zahlung ohne Beleg“ (Input für Teil B).

## Ist-Stand

- Buchhaltungsversion 1.0 → Kategorien = `AccountingType`.
- Mehrere Zahlungskonten (online + offline-Verrechnungskonten).
- Großer Rückstand nicht zugeordneter Umsätze, auch vor 2025 (bleibt unberührt).
- Belegentwürfe aus GetMyInvoices, teils USD/andere Währungen, teils Duplikate oder unplausible Daten (OCR).
- Umsätze ohne Dokument wurden bisher als Beleg ohne Dokument gebucht (Lohn/Gehalt, Krankenkasse, bezahlte USt, Miete, Gebühren). Einzelne Fehlbuchungen in der Historie dürfen nicht gelernt werden.
- Konkrete Zahlen der API-Probe liegen nur lokal (nicht im Repo).

## Harte Regeln

1. Nur Objekte mit Datum ≥ 2025-01-01. Abarbeitung neu → alt.
2. Ausgangsrechnungen, Gutschriften, Stornorechnungen: nie Status, Inhalt ändern oder löschen. Einzig erlaubt: Zahlung zuordnen (`Invoice/{id}/bookAmount`); dass sevDesk dadurch auf bezahlt setzt, ist ok.
3. Ein Beleg wird erst zugeordnet, wenn alle Korrekturen geschrieben **und** per Re-Read bestätigt sind (nach Zuordnung ist er gesperrt).
4. Nie löschen. Duplikate nur melden.
5. Jeder Schreibzugriff läuft über `actions.py`, prüft Regeln 1–4 selbst, unterstützt `--dry-run` und wird protokolliert.
6. Token nur aus macOS Keychain (`ww-gf-cockpit-sevdesk`), nie in Dateien oder Ausgaben.

## Ablauf `run`

1. **Laden (GET):** Belegentwürfe (50) und offene Eingangsbelege (100), offene Ausgangsrechnungen, Umsätze Status 100, bezahlte Belege ab 2025 (Historie), `AccountingType`, Zahlungskonten. Filter ≥ 2025-01-01.
2. **Lernen:** Lieferant → Kategorie + Steuerart aus Historie (nur wenn ≥ 2 Buchungen, alle gleich). Standardbuchungs-Regeln aus `standardbuchungen.json`.
3. **Beleg prüfen:** Pflichtfelder, Datum plausibel (≥ 2025, ≤ heute), Duplikat, Kategorie, Steuer, Währung.
4. **Kandidaten suchen** je Beleg/Rechnung/Umsatz.
5. **Einstufen:** sicher → ausführen, sonst → Review-Liste, kein Kandidat → „Zahlung ohne Beleg“.
6. **Ausführen (sicher):**
   - Eingangsbeleg: korrigieren (Kategorie; bei USD Euro-Betrag = Bankbetrag) → Re-Read + Vergleich → Entwurf auf offen (falls API das verlangt) → `Voucher/{id}/bookAmount` mit Umsatz.
   - Ausgangsrechnung: nur `Invoice/{id}/bookAmount`.
   - Standardbuchung: Beleg ohne Dokument anlegen (VOU, Ausgabe, Buchungsart, Betrag, Datum = Valutadatum, Lieferant = Empfänger) → Re-Read → `bookAmount`.
7. **Bericht:** erledigt / Review / ohne Beleg / Duplikate, je Anzahl und Summe.

Befehle: `run [--dry-run] [--limit N]`, `review`, `status`. `--limit` (Default 20) begrenzt Schreibvorgänge pro Lauf in der Startphase.

## Regeln „sicher“

Alle Bedingungen müssen gelten, sonst Review.

**Eingangsbeleg ↔ Zahlung**
1. Datum 2025-01-01 … heute.
2. Kein Duplikat (Lieferant + Betrag + Datum).
3. Kategorie: entspricht gelernter, oder leer und Lieferant ≥ 2× mit derselben gebucht.
4. Steuerart/-satz wie Historie des Lieferanten.
5. Betrag EUR: centgenau. USD: Abweichung Bank-EUR zu sevDesk-EUR ≤ 3 % → Beleg auf Bank-EUR anpassen. Andere Währungen: immer Review.
6. Zahlungsdatum zwischen Belegdatum −5 und +45 Tagen.
7. Eindeutig in beide Richtungen (1 Umsatz ↔ 1 Beleg).
8. Lieferantenname (unscharf) in Empfänger oder Verwendungszweck.
9. Betrag ≤ 2.000 €.

**Ausgangsrechnung ↔ Zahlungseingang**
- Rechnungsnummer im Verwendungszweck, Betrag = offener Betrag centgenau, genau ein Kandidat.
- Teil-/Sammelzahlung, Gutschrift, Storno: immer Review.

**Standardbuchung (Umsatz ohne Dokument)**
- Genau eine Regel aus `standardbuchungen.json` passt, Empfänger bekannt.
- Lohn/Krankenkasse/Miete: Betrag ±10 % zum Vormonat desselben Empfängers (keine 2.000-€-Grenze).
- Bankgebühren: ≤ 100 €.
- Finanzamt: immer Review, Vorschlag der Buchungsart aus Verwendungszweck (USt/LSt/KSt/GewSt).
- Miete: Standardbuchung erlaubt, Mietvertrag einmalig als Dokument hinterlegen (manuell).

Alles mit Beleg-Pflicht ohne Kandidat → „Zahlung ohne Beleg“.

Grenzwerte in `config.ini` (keine Secrets): `usd_toleranz_prozent=3`, `tage_vorher=5`, `tage_nachher=45`, `max_betrag=2000`, `min_historie=2`, `lohn_toleranz_prozent=10`, `gebuehren_max=100`.

## Bausteine

| Datei | Zweck |
|---|---|
| `sevdesk-belege/cli.py` | Befehle `run`, `review`, `status` |
| `sevdesk-belege/rules.py` | reine Funktionen: prüfen, lernen, Kandidaten, einstufen, USD, Duplikate — kein API-Zugriff |
| `sevdesk-belege/actions.py` | alle Schreibzugriffe, Guards (harte Regeln), Dry-Run, Protokoll |
| `sevdesk-belege/db.py` | SQLite `data.db`: Protokoll, Review-Liste, Entscheidungen |
| `sevdesk-belege/standardbuchungen.json` | Regeln Empfänger/Zweck-Muster → Buchungsart; initial aus Historie erzeugt, danach editierbar |
| `sevdesk-belege/config.ini` | Grenzwerte |
| `shared/sevdesk_client.py` | + `put`, Retry bei 429/5xx, Token aus Keychain |
| `shared/secrets.py` | `keychain_token(service)` |

`sevdesk-mahnwesen` stellt auf Keychain-Token um.

## Datenmodell (SQLite)

- `runs(id, start, ende, dry_run, erledigt, review, ohne_beleg)`
- `actions(id, run_id, ts, objekt_typ, objekt_id, aktion, payload_json, ergebnis, fehler, dry_run)` — vor jedem Schreibvorgang Eintrag „geplant“, danach „ok“/„fehler“.
- `review(id, art, beleg_id, umsatz_id, grund, vorschlag_json, status[offen|angenommen|geändert|übersprungen], entschieden_am)`

Kein Cache von sevDesk-Daten — jeder Lauf liest frisch (sevDesk ist Wahrheit, Läufe sind idempotent).

## Fehlerfälle

- API-Fehler bei Korrektur → Fall abbrechen, nicht zuordnen, Review mit Fehlertext.
- Re-Read weicht ab → nicht zuordnen, Review.
- Beleg auf offen gesetzt, Zuordnung schlägt fehl → Review „offen, nicht zugeordnet“; nächster Lauf findet ihn als offenen Eingangsbeleg wieder.
- 429/5xx → Retry mit Backoff (3×), dann Fall abbrechen.
- Guard-Verletzung (Datum < 2025, Ausgangsrechnung Status) → Exception, Lauf stoppt komplett.

## Tests

- `tests/test_rules.py` (pytest): Einstufung je Regel mit Fixtures aus anonymisierten echten Daten — USD-Toleranz an Grenze, Duplikat, zwei Kandidaten, Datum 2030, Datum < 2025, unbekannter Lieferant, Kategorie-Ausreißer, Finanzamt immer Review, Lohn ±10 %, Gutschrift immer Review.
- `tests/test_actions.py`: Fake-Client zeichnet Aufrufe auf. Prüft: Dry-Run schreibt nie; Guards werfen bei Datum < 2025 und bei jedem Invoice-Aufruf außer `bookAmount`; Reihenfolge Korrektur → Re-Read → Zuordnung; kein Zuordnen nach fehlgeschlagenem Re-Read.
- Abnahme: `run --dry-run` gegen echtes sevDesk (nur GET), Bericht mit dir durchgehen. Danach erster echter Lauf mit `--limit 1`, Ergebnis in sevDesk kontrollieren, dann schrittweise erhöhen.

## Offen / in Planung zu verifizieren

- sevDesk 1.0: muss Entwurf (50) vor `bookAmount` auf 100 gesetzt werden? Endpunkt zum Anlegen/Ändern (`Voucher/Factory/saveVoucher`) und Pflichtfelder für Beleg ohne Dokument — per Probe an einem Testbeleg, nur mit Freigabe.
- Feld für offenen Betrag bei Ausgangsrechnungen (Teilzahlungen).

## Nicht Teil von A

- Belege beschaffen (Teil B, GetMyInvoices).
- Korrektur bereits zugeordneter Fehlbuchungen (gesperrt) → TODO für Steuerberater.
- Umsätze vor 2025.
- launchd-Zeitplan (kommt nach stabiler Startphase).
