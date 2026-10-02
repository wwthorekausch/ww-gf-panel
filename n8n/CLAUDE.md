# n8n

Import-Workflows für n8n (kein n8n-MCP angebunden → JSON importieren).

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

Stündlich bis zu 10 Rechnungen ab 01.01.2025 (Typ Eingangs-/Ausgangsrechnung) **ohne** Tag „KI-geprüft“ aus Paperless → Gemini 2.5 Flash (Agent, JSON-Schema) liest OCR-Text → Code-Knoten baut Änderungen → `PATCH` Custom Fields + Tag „KI-geprüft“ → Prüfnotiz am Dokument (Hinweis, Änderungen, Vorher-Werte).

- Felder werden nur bei Sicherheit ≥ 0,8 geändert; sonst nur Tag + Notiz. SevdeskID/Kundennummer/Korrespondent werden nie angefasst.
- Vorher-Werte stehen in der Notiz → manuell rückgängig machbar.

Nach dem Import:
1. In Paperless Tag **„KI-geprüft“** anlegen, ID notieren → in Knoten „Paperless: ungeprüfte Rechnungen“ (`tags__id__none`) und „Änderungen + Tag bauen“ (`KI_GEPRUEFT_TAG_ID`) eintragen.
2. Credentials: Header Auth „Paperless Token“ an den drei HTTP-Knoten, „Google Gemini (PaLM) API“ am Modell-Knoten.
3. Erst manuell mit 1–2 Dokumenten testen (page_size auf 1), Notizen prüfen, dann aktivieren.

## Selflearning

### Lessons

- Gemini (Agent + Structured Output Parser): keine Union-Typen `"type": ["string","null"]` im Schema → 400 „Proto field is not repeating“. Einfache Typen, Feld optional lassen.
