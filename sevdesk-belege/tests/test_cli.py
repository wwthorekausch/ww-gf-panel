import configparser
import sqlite3
from datetime import date

import actions
import cli
import db
from conftest import D
from modell import Fall, Standardregel, Umsatz


def test_lade_grenzen_aus_config():
    c = configparser.ConfigParser()
    c.read_string("[grenzen]\nmax_betrag = 500\nusd_toleranz_prozent = 2.5\n[kategorien]\nstandard_ids = 1, 2\n")
    g = cli.lade_grenzen(c)
    assert g.max_betrag == D("500") and g.usd_toleranz_prozent == D("2.5") and g.tage_nachher == 45
    assert g.standard_kategorie_ids == frozenset({"1", "2"})


def test_regeln_roundtrip(tmp_path):
    p = tmp_path / "standardbuchungen.json"
    regeln = [Standardregel("Bankgebühren", "entgelt", "gebuehren", "70", "Bank")]
    cli.speichere_regeln(p, regeln)
    assert cli.lade_regeln(p) == regeln


class StubSchreiber:
    def __init__(self, fehler=None, limit_nach=None):
        self.fehler, self.limit_nach, self.n = fehler, limit_nach, 0

    def ausfuehren(self, fall, kategorie_id=None):
        if self.limit_nach is not None and self.n >= self.limit_nach:
            raise actions.LimitErreicht("x")
        self.n += 1
        if self.fehler:
            raise actions.Abbruch(self.fehler)
        return "ok"


def fall(i):
    u = Umsatz(str(i), "1", date(2026, 9, i), D("-1"), "n", "z")
    return Fall("standard", True, "Standardbuchung", u.datum, umsatz=u,
                regel=Standardregel("R", "n", "gebuehren", "70", "Bank"))


def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    db.init(c)
    return c


def test_verarbeite_zaehlt_und_stoppt_bei_limit():
    z = cli.verarbeite([fall(1), fall(2), fall(3)], StubSchreiber(limit_nach=2), conn())
    assert z == {"erledigt": 2, "abgebrochen": 0, "limit": True}


def test_verarbeite_abbruch_kommt_in_review():
    c = conn()
    z = cli.verarbeite([fall(1)], StubSchreiber(fehler="Nachlesen weicht ab"), c)
    assert z == {"erledigt": 0, "abgebrochen": 1, "limit": False}
    assert tuple(c.execute("SELECT status, grund FROM review").fetchone()) == ("offen", "Nachlesen weicht ab")
