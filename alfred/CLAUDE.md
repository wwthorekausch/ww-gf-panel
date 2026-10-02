# alfred

Alfred-5-Workflow (Powerpack nötig) zum Starten der Cockpit-Jobs.

- Bauen: `python3 alfred/bauen.py` → `alfred/GF-Cockpit.alfredworkflow` (gitignored), Doppelklick = Import
- Keyword `gf` + Suchtext: Liste aus `JOBS` (`cockpit.py alfred <suche>`), neue Jobs erscheinen automatisch
- Enter: Job im Terminal (Alfred-Einstellung *Features → Terminal* bestimmt die App) — nötig für j/n-Rückfragen
- ⌘+Enter: nur lesende Jobs im Hintergrund, letzte 3 Zeilen als Mitteilung; ✎-Jobs dort gesperrt
- Pfade zu Python/cockpit.py werden beim Bauen eingesetzt → nach Umzug oder Python-Wechsel neu bauen und importieren
