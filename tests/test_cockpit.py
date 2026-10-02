import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import cockpit


def test_jobs_eindeutig_und_module_existieren():
    namen = [j.name for j in cockpit.JOBS]
    assert len(namen) == len(set(namen))
    for j in cockpit.JOBS:
        assert (cockpit.ROOT / j.modul / "cli.py").exists(), j.modul


def test_job_finden():
    assert cockpit.finde_job("sevdesk-vorschau").argumente[0] == "run"
    assert cockpit.finde_job("3") == cockpit.JOBS[2]
    assert cockpit.finde_job("gibtsnicht") is None


def test_schreibende_jobs_markiert():
    assert cockpit.finde_job("sevdesk-buchen").schreibt and not cockpit.finde_job("sevdesk-vorschau").schreibt


def test_alfred_liste_filtert_und_sperrt_hintergrund_fuer_schreibende():
    items = cockpit.alfred_items("mahn")
    assert [i["arg"] for i in items] == ["mahnungen", "offene-posten"]
    assert items[0]["mods"]["cmd"]["valid"] is True
    buchen = cockpit.alfred_items("sevdesk-buchen")[0]
    assert buchen["title"].startswith("✎") and buchen["mods"]["cmd"]["valid"] is False
    assert len(cockpit.alfred_items("")) == len(cockpit.JOBS)
