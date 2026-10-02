# Testplan GF-Cockpit

Alle Befehle für **fish**, von jedem Ordner aus. Reihenfolge einhalten: erst lesen (🔍), dann schreiben (✎).
Haken setzen, wenn das Ergebnis passt. Bei Abweichung: Ausgabe kopieren und melden.

## 0 · Einmalig vorbereiten

- [ ] Alias anlegen

  ```fish
  alias --save cockpit 'python3 "/Users/thorekausch/Documents/workplaces/ww/WW KI Themen/WW-GF-Cockpit/cockpit.py"'
  ```

- [ ] Keychain-Einträge vorhanden (jede Zeile gibt den Namen aus, keinen Fehler)

  ```fish
  for s in ww-gf-cockpit-sevdesk ww-gf-cockpit-getmyinvoices ww-gf-cockpit-paperless
      security find-generic-password -s $s >/dev/null; and echo "ok $s"; or echo "FEHLT $s"
  end
  ```

- [ ] Menü erscheint mit 12 Jobs: `cockpit` → mit `q` beenden

## 1 · sevDesk

- [ ] 🔍 **Vorschau** — `cockpit job sevdesk-vorschau`
  Erwartet: Liste „sicher“ + Zusammenfassung (`sicher / review / ohne_beleg / beleg_ohne_zahlung`), Zeile `DRY-RUN — nichts geschrieben`.
- [ ] 🔍 **Status** — `cockpit job sevdesk-status`
  Erwartet: letzte Läufe mit `live`/`dry`, erledigt-Zahlen.
- [ ] ✎ **Buchen** — `cockpit job sevdesk-buchen` → Rückfrage mit `j`
  Erwartet: `geschrieben: N erledigt, 0 abgebrochen`. Bei N > 0 eine Buchung in sevDesk stichprobenartig öffnen: Beleg „bezahlt“, Umsatz zugeordnet.
- [ ] ✎ **Review** — `cockpit job sevdesk-review` → Rückfrage `j`
  Erwartet: Fälle einzeln mit Grund. Einen Fall mit `Enter` überspringen, einen mit `n` ablehnen, dann `q`. Erneut starten: abgelehnter Fall taucht nicht mehr auf.
- [ ] ✎ **Duplikate** — `cockpit job sevdesk-duplikate` → `j`
  Erwartet: aktuell `0 Duplikat-Gruppen` (oder neue Paare mit gleicher Belegnummer). Am Ende Liste „fehlendem/zukünftigem Datum“ (Shopify 2030).

## 2 · GetMyInvoices

- [ ] 🔍 **Suche** — `cockpit job gmi-suche`
  Erwartet: Tabelle `nur_gmi / in_sevdesk / mehrdeutig / nicht_gefunden`, Datei `sevdesk-belege/gmi_bericht.csv` aktualisiert.
- [ ] ✎ **Taggen** — `cockpit job gmi-taggen` → `j`
  Erwartet: `0 Dokumente mit 'Sevdesk' getaggt, N hatten den Tag schon` (alles schon erledigt). In GetMyInvoices Filter Tag „Sevdesk“ → ca. 277 Dokumente.
- [ ] Manuell: PDFs aus GetMyInvoices (Tag „Sevdesk“) in sevDesk hochladen → danach `cockpit job sevdesk-vorschau`: neue Entwürfe erscheinen als „sicher“ oder „review“.

## 3 · Paperless

- [ ] 🔍 **Duplikate anzeigen** — `cockpit job paperless-duplikate`
  Erwartet: `0 Duplikat-Gruppen` oder wenige neue (n8n lädt evtl. doppelt).
- [ ] ✎ **Duplikate löschen** — `cockpit job paperless-duplikate-loeschen` → `j`, je Gruppe `j`
  Erwartet: `gelöscht #…`, Eintrag in `paperless/loeschprotokoll.csv`, Dokument im Paperless-Papierkorb.
- [ ] 🔍 **Anreichern Vorschau** — `cockpit job paperless-vorschau`
  Erwartet: `N zu ergänzen` (nur neue Dokumente seit letztem Lauf), `fehlt_in_sevdesk.csv` aktualisiert.
- [ ] ✎ **Anreichern** — `cockpit job paperless-anreichern` → `j`
  Erwartet: `geschrieben: N Dokumente`. Ein Dokument in Paperless öffnen: Custom Fields, Korrespondent, Speicherpfad „Belege“.
- [ ] ✎ **Korrigieren** — `cockpit job paperless-korrigieren` → `j`
  Prüffälle:
  - [ ] **#181 / 160202127** (DigitalOcean-Receipt): Rechnungsnummer 24114, Firma/Korrespondent Vicci → leer. Mit `j` übernehmen.
  - [ ] **#176 Telekom**: Netto → `EUR136.63`. Mit `j` übernehmen.
  - [ ] **Anthropic / DigitalOcean** mit Korrespondent „SH-Kiel_HRB“ → richtiger Korrespondent. Mit `j` übernehmen.
  - [ ] **Marketplace-Gebühren** Zahlart Paypal → Lastschrift: selbst entscheiden (`Enter` = lassen).
  Danach erneut `cockpit job paperless-korrigieren`: übernommene Fälle tauchen nicht mehr auf.

## 4 · Automatisierung: täglicher Lauf (launchd)

> Erst starten, wenn 1–3 einzeln geprüft sind. Der Lauf führt `sevdesk-buchen` und `gmi-suche` ohne Rückfrage aus.

- [ ] Installieren und sofort testen

  ```fish
  cp "/Users/thorekausch/Documents/workplaces/ww/WW KI Themen/WW-GF-Cockpit/launchd/de.webwikinger.gf-cockpit.plist" ~/Library/LaunchAgents/
  launchctl load ~/Library/LaunchAgents/de.webwikinger.gf-cockpit.plist
  launchctl start de.webwikinger.gf-cockpit
  ```

  Keychain-Abfrage ggf. mit „Immer erlauben“ bestätigen.
- [ ] Nach ca. 1–3 Minuten: macOS-Mitteilung „GF-Cockpit“ erscheint.
- [ ] Log prüfen: `tail -40 ~/Library/Logs/ww-gf-cockpit/(date +%F).log` → beide Abschnitte, `Ende rc=0/0`.
- [ ] Bei Problemen: `cat /tmp/ww-gf-cockpit.err`

## 5 · n8n (Gmail → Paperless)

- [ ] Mail mit Label „GMI“ und PDF-Anhang anlegen → Workflow manuell ausführen.
  Erwartet: Dokument in Paperless (Typ + Tag „Eingangsrechnung“), Mail bekommt Label „paperless“.
- [ ] Workflow ein zweites Mal ausführen: dieselbe Mail wird nicht erneut verarbeitet.
- [ ] Danach `cockpit job paperless-duplikate`: kein neues Duplikat. Falls doch → Paperless liest diese Mails zusätzlich selbst ein (siehe Hinweis in [n8n/CLAUDE.md](n8n/CLAUDE.md)).

## 6 · Alfred

- [ ] Workflow bauen und importieren

  ```fish
  python3 "/Users/thorekausch/Documents/workplaces/ww/WW KI Themen/WW-GF-Cockpit/alfred/bauen.py"
  open "/Users/thorekausch/Documents/workplaces/ww/WW KI Themen/WW-GF-Cockpit/alfred/GF-Cockpit.alfredworkflow"
  ```

- [ ] `gf` → Liste aller Jobs; `gf mahn` filtert.
- [ ] `gf offene` + Enter → Terminal öffnet, `…/cockpit.py job offene-posten` läuft.
- [ ] `gf status` + ⌘+Enter → Mitteilung mit letzten Läufen. Bei ✎-Job ist ⌘+Enter gesperrt.

## 7 · Tests (optional)

```fish
cd "/Users/thorekausch/Documents/workplaces/ww/WW KI Themen/WW-GF-Cockpit"; and python3 -m pytest -q
```

Erwartet: alles `passed`.
