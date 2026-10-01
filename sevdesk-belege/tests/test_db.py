import sqlite3

import db


def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    db.init(c)
    return c


def test_protokoll_geplant_dann_ergebnis():
    c = conn()
    run = db.run_start(c, dry_run=True)
    aid = db.log_geplant(c, run, "Voucher", "5", "zuordnen", {"amount": 1.5}, True)
    db.log_ergebnis(c, aid, "dry-run")
    row = c.execute("SELECT * FROM actions").fetchone()
    assert (row["aktion"], row["ergebnis"], row["dry_run"], row["payload_json"]) == ("zuordnen", "dry-run", 1, '{"amount": 1.5}')


def test_review_abgelehnt():
    c = conn()
    db.review_merken(c, "beleg", "5", "7", "Kategorie", "abgelehnt")
    db.review_merken(c, "beleg", "6", "8", "x", "angenommen")
    assert db.abgelehnt(c) == {("beleg", "5", "7")}


def test_run_ende_speichert_zahlen():
    c = conn()
    run = db.run_start(c, dry_run=False)
    db.run_ende(c, run, {"sicher": 3, "review": 2, "ohne_beleg": 1})
    r = db.letzte_runs(c)[0]
    assert (r["erledigt"], r["review"], r["ohne_beleg"], r["dry_run"]) == (3, 2, 1, 0)
