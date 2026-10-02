#!/usr/bin/env python3
"""Baut GF-Cockpit.alfredworkflow (Doppelklick = Import in Alfred).

Pfade zu Python und cockpit.py werden beim Bauen eingesetzt — nach Umzug des Ordners neu bauen.
"""
import plistlib
import shlex
import sys
import zipfile
from pathlib import Path

HIER = Path(__file__).resolve().parent
COCKPIT = HIER.parent / "cockpit.py"
ZIEL = HIER / "GF-Cockpit.alfredworkflow"

FILTER, TERMINAL, SKRIPT, MITTEILUNG = "gf-filter", "gf-terminal", "gf-skript", "gf-mitteilung"


def info(python: str, cockpit: Path) -> dict:
    aufruf = f"{shlex.quote(python)} {shlex.quote(str(cockpit))}"
    return {
        "bundleid": "de.webwikinger.gf-cockpit",
        "name": "GF-Cockpit",
        "description": "Cockpit-Jobs starten (sevDesk, Mahnwesen, GetMyInvoices, Paperless)",
        "createdby": "Web Wikinger",
        "objects": [
            {"uid": FILTER, "type": "alfred.workflow.input.scriptfilter", "version": 3, "config": {
                "keyword": "gf", "withspace": True, "argumenttype": 1, "title": "GF-Cockpit",
                "subtext": "Job suchen — Enter: Terminal, ⌘+Enter: Hintergrund",
                "runningsubtext": "lade Jobs …", "type": 0, "scriptargtype": 1, "escaping": 0,
                "alfredfiltersresults": False, "scriptfile": "",
                "script": f'{aufruf} alfred "$1"'}},
            {"uid": TERMINAL, "type": "alfred.workflow.action.terminalcommand", "version": 1, "config": {
                "script": f"{aufruf} job {{query}}", "escaping": 0}},
            {"uid": SKRIPT, "type": "alfred.workflow.action.script", "version": 2, "config": {
                "type": 0, "scriptargtype": 1, "escaping": 0, "concurrently": False, "scriptfile": "",
                "script": f'{aufruf} job "$1" 2>&1 | tail -n 3'}},
            {"uid": MITTEILUNG, "type": "alfred.workflow.output.notification", "version": 1, "config": {
                "title": "GF-Cockpit", "text": "{query}", "onlyshowifquerypopulated": True,
                "lastpathcomponent": False, "removeextension": False}},
        ],
        "connections": {
            FILTER: [
                {"destinationuid": TERMINAL, "modifiers": 0, "modifiersubtext": "", "vitoclose": False},
                {"destinationuid": SKRIPT, "modifiers": 1048576, "modifiersubtext": "", "vitoclose": False},
            ],
            SKRIPT: [{"destinationuid": MITTEILUNG, "modifiers": 0, "modifiersubtext": "", "vitoclose": False}],
        },
        "uidata": {FILTER: {"xpos": 30, "ypos": 100}, TERMINAL: {"xpos": 300, "ypos": 30},
                   SKRIPT: {"xpos": 300, "ypos": 170}, MITTEILUNG: {"xpos": 500, "ypos": 170}},
    }


def main() -> int:
    with zipfile.ZipFile(ZIEL, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("info.plist", plistlib.dumps(info(sys.executable, COCKPIT)))
    print(f"gebaut: {ZIEL}\nDoppelklick zum Import, Keyword: gf")
    return 0


if __name__ == "__main__":
    sys.exit(main())
