"""Gemeinsamer INI-Config-Loader für alle Cockpit-Module."""
import configparser
from pathlib import Path


def load_config(module_dir: Path, filename: str = "config.ini") -> configparser.ConfigParser:
    """Lädt config.ini aus dem Modul-Ordner. Bricht mit klarer Meldung ab, falls Datei fehlt."""
    config_path = module_dir / filename
    if not config_path.exists():
        raise FileNotFoundError(
            f"{config_path} nicht gefunden. Siehe CLAUDE.md im Modul-Ordner für Setup."
        )
    config = configparser.ConfigParser()
    config.read(config_path)
    return config
