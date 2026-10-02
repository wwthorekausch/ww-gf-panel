# n8n

Import-Workflows für n8n. Instanz: https://n8n.web-wikinger.de = **GF-n8n der Web Wikinger** (Geschäftsführung, nicht Kunden/Team).

## MCP

`n8n-gf` (Paket `n8n-mcp`) per `claude mcp add --scope local n8n-gf -- <pfad>/n8n/mcp-start.sh` — nur in diesem Projekt, nicht global. API-Key nur aus Keychain `ww-gf-cockpit-n8n` (n8n → Settings → n8n API). Schreibende MCP-Aufrufe (Workflow anlegen/ändern/aktivieren/löschen, Ausführung starten) nur nach Einzel-Freigabe; lesen frei.

## gmail-gmi-zu-paperless.json

Alle 30 Min: Gmail-Mails mit Label `GMI` ohne Label `paperless` (mit Anhang, max. 50) → jeder PDF-Anhang per `POST /api/documents/post_document/` nach Paperless → danach Label `paperless` an die Mail (erst nach erfolgreichem Upload; bei Fehler Retry im nächsten Lauf, Paperless erkennt Datei-Duplikate).

Nach dem Import in n8n:
1. Credential **Gmail OAuth2** an beiden Gmail-Knoten wählen.
2. Credential **Header Auth** anlegen: Name `Authorization`, Wert `Token <paperless-token>` → am HTTP-Knoten wählen.
3. Im Knoten „Gmail: Label paperless setzen“ das Label `paperless` auswählen (Label vorher in Gmail anlegen).
4. Einmal manuell testen, dann aktivieren.

Upload setzt Dokumenttyp `1` (Eingangsrechnung) und Tag `3` (Eingangsrechnung) — Paperless-IDs, keine Namen. Weitere Tags: zusätzliches Body-Feld `tags` mit weiterer ID.

Doppelte Anhänge (gleicher Dateiname + Größe) werden pro Lauf nur einmal hochgeladen; die Mail bekommt trotzdem das Label. Paperless erkennt zusätzlich inhaltsgleiche Dateien.

Bekannte Grenze: Mails mit Anhang, aber ohne PDF, bekommen kein Label und werden jeden Lauf erneut gelesen (harmlos; ggf. manuell labeln).

## paperless-gemini-pruefung.json

Stündlich bis zu 10 Rechnungen ab 01.01.2025 (Typ Eingangs-/Ausgangsrechnung) **ohne** Tag „KI-geprüft“ aus Paperless → Gemini 2.5 Flash (Agent, JSON-Schema) liest OCR-Text → Korrespondenten laden (einmal je Lauf) → Code-Knoten baut Änderungen → ggf. Korrespondent anlegen → `PATCH` Custom Fields + Korrespondent + Tag „KI-geprüft“ → Prüfnotiz am Dokument (Hinweis, Änderungen, Vorher-Werte).

- OCR hat Vorrang (Entscheidung 2026-10-02): Felder und Korrespondent werden bei Sicherheit ≥ 0,8 aus dem OCR-Text gesetzt; sonst nur Tag + Notiz. SevdeskID/Kundennummer werden nie angefasst.
- Korrespondent = Firma aus OCR: bleibt, wenn der aktuelle ähnlich ist (Regel wie `paperless/anreichern.py` `aehnlich`); sonst exakter Namenstreffer, sonst genau ein ähnlicher, sonst neu anlegen. Grenze: dieselbe neue Firma zweimal im selben Lauf → zweites Anlegen schlägt fehl (nächster Lauf greift den Treffer).
- Vorher-Werte stehen in der Notiz → manuell rückgängig machbar.

Nach dem Import:
1. Tag **„KI-geprüft“** = ID `18` (in Knoten „Paperless: ungeprüfte Rechnungen“ `tags__id__none` und „Änderungen + Tag bauen“ eingetragen).
2. Credentials: Header Auth „Paperless Token“ an den fünf HTTP-Knoten, „Google Gemini (PaLM) API“ am Modell-Knoten.
3. Erst manuell mit 1–2 Dokumenten testen (page_size auf 1), Notizen prüfen, dann aktivieren.

## Selflearning

### Lessons

- Gemini (Agent + Structured Output Parser): keine Union-Typen `"type": ["string","null"]` im Schema → 400 „Proto field is not repeating“. Einfache Typen, Feld optional lassen.
