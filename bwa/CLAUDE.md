# bwa

Monatliche Auswertung der DATEV-BWA (Kurzfristige Erfolgsrechnung) vom Steuerberater.

- `data/YYYY-MM.json` — Rohdaten je Monat: `zeilen` (BWA-Zeilen 1020–1380) und `konten` (Einzelkonten mit Zuordnung `zeile`), jeweils `monat` + `kum` (kumuliert ab Januar); Zeilen zusätzlich `vj_monat` + `vj_kum` (Vorjahr aus BWA-PDF). Original-PDFs: `BWAmm.pdf` (BWA mit Vorjahr), `KERmm.pdf` (Kurzfr. Erfolgsrechnung mit Konten).
- `auswertungen/YYYY-MM.md` — Kennzahlen, Top 5, Gut/Schlecht, offene Fragen.

Ablauf neuer Monat: BWA-Text einfügen → JSON anlegen → Summencheck (Konten je Zeile = Zeilenwert) → Vergleich mit Vormonat (`monat`) und Ø Vormonate ((kum − monat) / (Monate − 1)) → Auswertung schreiben, offene Fragen aus Vormonat nachhalten.

Kein `cli.py` bisher — reine Datenablage.
