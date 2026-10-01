#!/usr/bin/env python3
"""Zentraler Dispatcher: leitet Befehle an das cli.py eines Modul-Unterordners weiter."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent


def main() -> int:
    if len(sys.argv) < 2:
        modules = sorted(p.name for p in ROOT.iterdir() if p.is_dir() and (p / "cli.py").exists())
        print("Nutzung: python cockpit.py <modul> <befehl> [args...]")
        print("Verfügbare Module:", ", ".join(modules) or "(keine gefunden)")
        return 1

    module = sys.argv[1]
    module_cli = ROOT / module / "cli.py"
    if not module_cli.exists():
        print(f"Modul '{module}' nicht gefunden (erwartet: {module_cli})")
        return 1

    return subprocess.call([sys.executable, str(module_cli), *sys.argv[2:]])


if __name__ == "__main__":
    sys.exit(main())
