# launchd

Täglicher Lauf 07:00 (`taeglich.sh`): `cockpit job sevdesk-buchen --ja` (sichere Buchungen, alle Schutzregeln) + `cockpit job gmi-suche` (nur Bericht). Log `~/Library/Logs/ww-gf-cockpit/YYYY-MM-DD.log`, macOS-Mitteilung mit Ergebnis bzw. Warnung bei Stopp/Fehler.

## Installieren / Entfernen (fish)

    cp "/Users/thorekausch/Documents/workplaces/ww/WW KI Themen/WW-GF-Cockpit/launchd/de.webwikinger.gf-cockpit.plist" ~/Library/LaunchAgents/
    launchctl load ~/Library/LaunchAgents/de.webwikinger.gf-cockpit.plist
    launchctl start de.webwikinger.gf-cockpit        # sofort einmal testen

    launchctl unload ~/Library/LaunchAgents/de.webwikinger.gf-cockpit.plist   # entfernen

Nur Jobs ohne Rückfrage hier eintragen. Keychain muss entsperrt sein (eingeloggt).

## Selflearning

### Lessons
