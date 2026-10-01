# n8n

Import-Workflows für n8n (kein n8n-MCP angebunden → JSON importieren).

## gmail-gmi-zu-paperless.json

Alle 30 Min: Gmail-Mails mit Label `GMI` ohne Label `paperless` (mit Anhang, max. 50) → jeder PDF-Anhang per `POST /api/documents/post_document/` nach Paperless → danach Label `paperless` an die Mail (erst nach erfolgreichem Upload; bei Fehler Retry im nächsten Lauf, Paperless erkennt Datei-Duplikate).

Nach dem Import in n8n:
1. Credential **Gmail OAuth2** an beiden Gmail-Knoten wählen.
2. Credential **Header Auth** anlegen: Name `Authorization`, Wert `Token <paperless-token>` → am HTTP-Knoten wählen.
3. Im Knoten „Gmail: Label paperless setzen“ das Label `paperless` auswählen (Label vorher in Gmail anlegen).
4. Einmal manuell testen, dann aktivieren.

Doppelte Anhänge (gleicher Dateiname + Größe) werden pro Lauf nur einmal hochgeladen; die Mail bekommt trotzdem das Label. Paperless erkennt zusätzlich inhaltsgleiche Dateien.

Bekannte Grenze: Mails mit Anhang, aber ohne PDF, bekommen kein Label und werden jeden Lauf erneut gelesen (harmlos; ggf. manuell labeln).

## Selflearning

### Lessons
