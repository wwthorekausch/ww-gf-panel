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
