from datetime import date

import gmi
from conftest import D
from modell import Grenzen, Umsatz

G = Grenzen()


def dok(uid=1, firma="Beispiel Hosting GmbH", nr="R-1001", datum="2026-09-01", brutto=49.99, waehrung="EUR", typ="INCOMING_INVOICE"):
    return gmi.parse_dok({"documentUid": uid, "companyName": firma, "documentNumber": nr, "documentDate": datum,
                          "grossAmount": brutto, "currency": waehrung, "documentType": typ, "paymentStatus": "Paid"})


def ums(betrag="-49.99", datum=date(2026, 9, 3), name="BEISPIEL HOSTING", zweck="R-1001"):
    return Umsatz("u1", "1", datum, D(betrag), name, zweck)


def test_parse_dok():
    d = dok()
    assert (d.uid, d.firma, d.nr, d.datum, d.brutto, d.waehrung) == ("1", "Beispiel Hosting GmbH", "R-1001", date(2026, 9, 1), D("49.99"), "EUR")


def test_kandidat_eur_exakt_und_name():
    assert [d.uid for d in gmi.kandidaten(ums(), [dok(), dok(uid=2, brutto=50)], G)] == ["1"]


def test_kandidat_nur_ueber_belegnummer():
    assert gmi.kandidaten(ums(name="PAYPAL", zweck="Zahlung R-1001"), [dok()], G)


def test_kandidat_name_und_nummer_fehlen():
    assert gmi.kandidaten(ums(name="Fremd AG", zweck="x"), [dok()], G) == []


def test_kandidat_usd_toleranz():
    usd = dok(brutto=55.05, waehrung="USD", firma="Bitwarden")
    assert gmi.kandidaten(ums(betrag="-55.82", name="BITWARDEN", zweck=""), [usd], G) == []   # USD-Brutto != EUR
    usd_eur = dok(brutto=55.0, waehrung="EUR", firma="Bitwarden")
    assert gmi.kandidaten(ums(betrag="-55.82", name="BITWARDEN", zweck=""), [usd_eur], G) == []


def test_kandidat_zeitfenster():
    assert gmi.kandidaten(ums(datum=date(2026, 10, 17)), [dok()], G) == []   # 46 Tage nach Belegdatum


def test_kandidat_eingang_ignoriert():
    assert gmi.kandidaten(ums(betrag="49.99"), [dok()], G) == []


def test_einstufen():
    docs = [dok(uid=1, nr="R-1001"), dok(uid=2, nr="R-2002", brutto=10, firma="Andere GmbH")]
    u1, u2 = ums(), Umsatz("u2", "1", date(2026, 9, 3), D("-10"), "ANDERE GMBH", "")
    u3 = Umsatz("u3", "1", date(2026, 9, 3), D("-7"), "Niemand", "")
    erg = gmi.einstufen([u1, u2, u3], docs, sevdesk_nummern={"R-1001"}, grenzen=G)
    assert [(e.umsatz.id, e.status) for e in erg] == [("u1", "in_sevdesk"), ("u2", "nur_gmi"), ("u3", "nicht_gefunden")]


def test_einstufen_mehrdeutig():
    docs = [dok(uid=1, nr="A"), dok(uid=2, nr="B")]
    erg = gmi.einstufen([ums(zweck="")], docs, sevdesk_nummern=set(), grenzen=G)
    assert erg[0].status == "mehrdeutig"


def test_kandidat_usd_plausibler_kurs():
    usd = dok(brutto=80, waehrung="USD", firma="Bitwarden", nr="F38-1")
    assert [d.uid for d in gmi.kandidaten(ums(betrag="-69.73", name="BITWARDEN", zweck=""), [usd], G)] == ["1"]


def test_mehrere_monate_naechster_gewinnt():
    aug, sep = dok(uid=1, nr="A", datum="2026-08-01"), dok(uid=2, nr="B", datum="2026-09-01")
    assert [d.uid for d in gmi.kandidaten(ums(datum=date(2026, 9, 2), zweck=""), [aug, sep], G)] == ["2"]


def test_mehrere_belegnummer_gewinnt():
    a, b = dok(uid=1, nr="R-1001"), dok(uid=2, nr="R-1002", datum="2026-09-02")
    assert [d.uid for d in gmi.kandidaten(ums(zweck="R-1002"), [a, b], G)] == ["2"]


# --- Hochladen-Entscheidung ---
from modell import LieferantWissen

W = {"beispiel hosting": LieferantWissen("2820", "default:19", D("0"))}


def test_upload_sicher():
    e = gmi.Ergebnis(ums(), "nur_gmi", dok())
    p = gmi.upload_plan(e, W, G)
    assert p.sicher and (p.kategorie_id, p.steuerart, p.satz, p.betrag) == ("2820", "default", D("19"), D("49.99"))


def test_upload_nicht_bei_tag_sevdesk():
    d = gmi.parse_dok({"documentUid": 1, "companyName": "Beispiel Hosting GmbH", "documentNumber": "R-1001",
                       "documentDate": "2026-09-01", "grossAmount": 49.99, "currency": "EUR", "tags": ["Sevdesk"]})
    assert not gmi.upload_plan(gmi.Ergebnis(ums(), "nur_gmi", d), W, G).sicher


def test_upload_ohne_wissen_review():
    assert gmi.upload_plan(gmi.Ergebnis(ums(), "nur_gmi", dok()), {}, G).grund == "Lieferant ohne Kategorie"


def test_upload_mehrere_steuersaetze_review():
    w = {"beispiel hosting": LieferantWissen("2820", "default:7,19", D("0"))}
    assert not gmi.upload_plan(gmi.Ergebnis(ums(), "nur_gmi", dok()), w, G).sicher


def test_upload_ueber_max_betrag_review():
    e = gmi.Ergebnis(ums(betrag="-2500"), "nur_gmi", dok(brutto=2500))
    assert not gmi.upload_plan(e, W, G).sicher


def test_upload_nur_bei_nur_gmi():
    assert not gmi.upload_plan(gmi.Ergebnis(ums(), "in_sevdesk", dok()), W, G).sicher


def test_upload_nicht_vor_stichtag():
    e = gmi.Ergebnis(ums(datum=date(2025, 1, 3)), "nur_gmi", dok(datum="2024-12-31"))
    p = gmi.upload_plan(e, W, G)
    assert not p.sicher and "2025" in p.grund


def test_einstufen_ohne_nummer_erkennt_hochgeladenen():
    d = dok(uid=5, nr="", firma="Beispiel Hosting GmbH")
    assert gmi.einstufen([ums(zweck="")], [d], sevdesk_nummern={"GMI-5"}, grenzen=G)[0].status == "in_sevdesk"
