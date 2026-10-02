from datetime import date
from decimal import Decimal

import mahnwesen as m

HEUTE = date(2026, 10, 2)
SCHWELLEN = (7, 14, 30)


def roh(id="1", nr="RE-1", datum="2026-09-01T00:00:00+02:00", ziel=14, brutto="119", bezahlt="0", typ="RE", status="200", kunde="Kunde A", knr="1001", origin=None):
    return {"id": id, "invoiceNumber": nr, "invoiceDate": datum, "timeToPay": ziel, "sumGross": brutto, "paidAmount": bezahlt,
            "invoiceType": typ, "status": status, "contact": {"name": kunde, "customerNumber": knr},
            "origin": {"id": origin, "objectName": "Invoice"} if origin else None}


def test_parse_faelligkeit_und_offen():
    r = m.parse(roh(bezahlt="19"))
    assert r.faellig == date(2026, 9, 15) and r.offen == Decimal("100") and r.kunde == "Kunde A" and r.kundennummer == "1001"


def test_ohne_zahlungsziel_sofort_faellig():
    assert m.parse(roh(ziel=None)).faellig == date(2026, 9, 1)


def test_tage_und_stufe():
    r = m.parse(roh())                       # fällig 15.09. -> 17 Tage
    assert m.tage_ueberfaellig(r, HEUTE) == 17 and m.mahnstufe(17, SCHWELLEN) == 2
    assert m.mahnstufe(3, SCHWELLEN) == 0 and m.mahnstufe(30, SCHWELLEN) == 3


def test_ueberfaellige_sortiert_und_ohne_bezahlte():
    a = m.parse(roh(id="1", datum="2026-08-01T00:00:00+02:00"))
    b = m.parse(roh(id="2", datum="2026-09-10T00:00:00+02:00"))
    c = m.parse(roh(id="3", datum="2026-09-30T00:00:00+02:00"))      # noch nicht fällig
    d = m.parse(roh(id="4", datum="2026-07-01T00:00:00+02:00", bezahlt="119"))
    assert [r.id for r in m.ueberfaellig([a, b, c, d], HEUTE)] == ["1", "2"]


def test_mahnungen_markieren_original():
    rechnungen = [m.parse(roh(id="1"))]
    mahnungen = [roh(id="9", nr="MA-1", typ="MA", origin="1")]
    assert m.gemahnt(mahnungen) == {"1": 1}


def test_offen_pro_kunde():
    rs = [m.parse(roh(id="1", kunde="A", datum="2026-08-01T00:00:00+02:00")), m.parse(roh(id="2", kunde="A")),
          m.parse(roh(id="3", kunde="B", datum="2026-09-30T00:00:00+02:00", brutto="50"))]
    z = m.offen_pro_kunde(rs, HEUTE)
    assert z[0] == ("A", Decimal("238"), Decimal("238"), 2) and z[1] == ("B", Decimal("50"), Decimal("0"), 1)


def test_gutschrift_mindert_offen():
    rs = [m.parse(roh(id="1", kunde="A")), m.parse(roh(id="2", kunde="A", typ="GU", brutto="-19"))]
    assert m.offen_pro_kunde(rs, HEUTE)[0][1] == Decimal("100")


def test_vor_2025_ignoriert():
    alt = m.parse(roh(id="1", datum="2024-12-31T00:00:00+01:00"))
    neu = m.parse(roh(id="2", datum="2025-01-01T00:00:00+01:00"))
    assert [r.id for r in m.ab_stichtag([alt, neu])] == ["2"]


# --- Mahnstufe/Frist aus sevDesk-Feldern (dunningLevel, reminderDeadline) statt fester Tage ---
def ma(id="9", origin="1", stufe="1", frist="2026-09-20T00:00:00+02:00", status="200", datum="2026-09-13T00:00:00+02:00", gesendet="2026-09-13"):
    return {"id": id, "invoiceType": "MA", "origin": {"id": origin}, "dunningLevel": stufe, "reminderDeadline": frist,
            "status": status, "invoiceDate": datum, "sendDate": gesendet}


def test_stufe_aus_dunninglevel():
    assert m.parse({**roh(), "dunningLevel": "2"}).stufe == 2 and m.parse(roh()).stufe == 0


def test_letzte_mahnung_je_rechnung():
    info = m.letzte_mahnungen([ma(id="8", stufe="1", datum="2026-08-01T00:00:00+02:00"), ma(id="9", stufe="2")])
    assert info["1"].stufe == 2 and info["1"].frist == date(2026, 9, 20) and info["1"].entwurf is False


def test_aktion_ohne_mahnung_frist_aus_zahlungsziel():
    r = m.parse(roh())                              # fällig 15.09.
    assert m.aktion(r, None, HEUTE) == ("mahnen", 1, date(2026, 9, 15))


def test_aktion_frist_der_mahnung_noch_offen():
    r = m.parse({**roh(), "dunningLevel": "1"})
    assert m.aktion(r, m.letzte_mahnungen([ma(frist="2026-10-05T00:00:00+02:00")])["1"], HEUTE) is None


def test_aktion_frist_der_mahnung_abgelaufen_naechste_stufe():
    r = m.parse({**roh(), "dunningLevel": "1"})
    assert m.aktion(r, m.letzte_mahnungen([ma()])["1"], HEUTE) == ("mahnen", 2, date(2026, 9, 20))


def test_aktion_entwurf_versenden():
    r = m.parse({**roh(), "dunningLevel": "1"})
    info = m.letzte_mahnungen([ma(status="100", gesendet=None, frist="2026-10-05T00:00:00+02:00")])["1"]
    assert m.aktion(r, info, HEUTE) == ("entwurf versenden", 1, date(2026, 10, 5))


def test_aktion_nicht_faellig():
    assert m.aktion(m.parse(roh(datum="2026-09-30T00:00:00+02:00")), None, HEUTE) is None


# --- Absprachen: Kunden nicht mahnen / bereits Inkasso ---
ABSPRACHEN = [{"kunde": "Beispiel'n'Shop", "aktion": "nicht_mahnen", "notiz": "Absprache GF"},
              {"kunde": "Muster Group", "aktion": "inkasso", "notiz": "beim Inkasso"}]


def test_absprache_findet_kunde_ohne_sonderzeichen():
    assert m.absprache("beispiel’n’shop GmbH", ABSPRACHEN)["aktion"] == "nicht_mahnen"
    assert m.absprache("The Muster Group GmbH & Co. KG", ABSPRACHEN)["aktion"] == "inkasso"
    assert m.absprache("Andere AG", ABSPRACHEN) is None


def test_absprache_mit_rechnungsnummer_nur_diese():
    a = [{"kunde": "Andere AG", "rechnung": "RE-1", "aktion": "nicht_mahnen", "notiz": "Ratenzahlung"}]
    assert m.absprache("Andere AG", a, "RE-1") and m.absprache("Andere AG", a, "RE-2") is None
