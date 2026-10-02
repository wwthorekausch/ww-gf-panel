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


# --- Mahnungs-Entwurf nur, wenn wirklich fällig ---
def test_mahnbar_ok():
    r = m.parse({**roh(nr="RE-5", datum="2026-09-01T00:00:00+02:00"), "dunningLevel": "1"})
    info = m.letzte_mahnungen([ma(origin="1")])["1"]          # Frist 20.09. abgelaufen
    assert m.mahnbar(r, info, [], HEUTE) == (True, "2. Mahnung", 2)


def test_mahnbar_nicht_bei_absprache_entwurf_vor_stichtag_oder_frist():
    r = m.parse(roh(kunde="Muster Group"))
    assert m.mahnbar(r, None, ABSPRACHEN, HEUTE)[0] is False
    r2 = m.parse({**roh(), "dunningLevel": "1"})
    entwurf = m.letzte_mahnungen([ma(status="100", gesendet=None)])["1"]
    assert m.mahnbar(r2, entwurf, [], HEUTE)[0] is False
    assert m.mahnbar(m.parse(roh(datum="2024-12-01T00:00:00+01:00")), None, [], HEUTE)[0] is False
    assert m.mahnbar(m.parse(roh(datum="2026-09-30T00:00:00+02:00")), None, [], HEUTE)[0] is False


# --- Mahnung versenden nur als Entwurf einer offenen Rechnung ab 2025 ohne Absprache ---
def test_sendbar_ok_und_guards():
    orig = m.parse(roh(nr="RE-7", datum="2026-06-01T00:00:00+02:00"))
    entwurf = {"id": "9", "invoiceType": "MA", "status": "100", "sendDate": None, "origin": {"id": "1"}}
    assert m.sendbar(entwurf, orig, [])[0] is True
    assert m.sendbar({**entwurf, "status": "200"}, orig, [])[0] is False            # schon versendet
    assert m.sendbar({**entwurf, "invoiceType": "RE"}, orig, [])[0] is False        # keine Mahnung
    assert m.sendbar(entwurf, m.parse(roh(kunde="Muster Group")), ABSPRACHEN)[0] is False
    assert m.sendbar(entwurf, m.parse(roh(bezahlt="119")), [])[0] is False          # nichts offen
    assert m.sendbar(entwurf, m.parse(roh(datum="2024-12-01T00:00:00+01:00")), [])[0] is False


def test_mail_text_enthaelt_eckdaten():
    t = m.mahn_mail(nummer="RE-7", datum=date(2026, 6, 1), betrag=Decimal("120.49"), frist=date(2026, 10, 9), stufe=1)
    assert t["subject"] == "Zahlungserinnerung zur Rechnung RE-7"
    assert "RE-7 vom 01.06.2026" in t["text"] and "120,49 €" in t["text"] and "09.10.2026" in t["text"]


def test_mail_wahl_rechnungsadresse_vor_haupt():
    w = lambda v, main="0", key="2": {"type": "EMAIL", "value": v, "main": main, "key": {"id": key}}
    assert m.waehle_mail([w("a@x.de"), w("rechnung@x.de", key="8")]) == "rechnung@x.de"
    assert m.waehle_mail([w("a@x.de", main="1"), w("b@x.de")]) == "a@x.de"
    assert m.waehle_mail([w("a@x.de"), w("b@x.de")]) is None
    assert m.waehle_mail([w("nur@x.de")]) == "nur@x.de"


def test_neue_frist_nur_wenn_alt_abgelaufen_und_neu_in_zukunft():
    assert m.neue_frist_ok(date(2025, 12, 11), date(2026, 10, 9), HEUTE) == (True, "ok")
    assert m.neue_frist_ok(date(2026, 10, 20), date(2026, 10, 9), HEUTE)[0] is False     # alte Frist läuft noch
    assert m.neue_frist_ok(date(2025, 12, 11), date(2026, 9, 30), HEUTE)[0] is False     # neue Frist in der Vergangenheit


# --- Mahngebühr erlassen (bookAmount 0 €, Typ O) nur wenn Rechnung bezahlt und nichts anderes offen ---
def test_gebuehr_erlassbar():
    ma_ = {"invoiceType": "MA", "status": "750", "sumGross": "0", "paidAmount": "0", "reminderCharge": "3",
           "invoiceDate": "2026-07-06T00:00:00+02:00"}
    bezahlt = {"status": "1000"}
    assert m.gebuehr_erlassbar(ma_, bezahlt) == (True, "ok")
    assert m.gebuehr_erlassbar({**ma_, "status": "1000"}, bezahlt)[0] is False          # schon erledigt
    assert m.gebuehr_erlassbar(ma_, {"status": "200"})[0] is False                      # Rechnung noch offen
    assert m.gebuehr_erlassbar({**ma_, "paidAmount": "142.8"}, bezahlt)[0] is False     # negativer Rest/Überzahlung
    assert m.gebuehr_erlassbar({**ma_, "invoiceDate": "2024-12-01T00:00:00+01:00"}, bezahlt)[0] is False
    assert m.gebuehr_erlassbar({**ma_, "invoiceType": "RE"}, bezahlt)[0] is False


def test_gebuehr_erlassbar_vor_2025_nur_mit_freigabe():
    alt = {"invoiceType": "MA", "status": "750", "sumGross": "0", "paidAmount": "0", "reminderCharge": "6",
           "invoiceDate": "2022-03-01T00:00:00+01:00"}
    assert m.gebuehr_erlassbar(alt, {"status": "1000"})[0] is False
    assert m.gebuehr_erlassbar(alt, {"status": "1000"}, auch_vor_2025=True) == (True, "ok")
    assert m.gebuehr_erlassbar({**alt, "paidAmount": "5"}, {"status": "1000"}, auch_vor_2025=True)[0] is False


def test_versendete_mahnung_zu_erledigter_rechnung_abschliessbar():
    ma_ = {"invoiceType": "MA", "status": "500", "sumGross": "0", "paidAmount": "0", "reminderCharge": "0",
           "invoiceDate": "2026-07-06T00:00:00+02:00"}
    assert m.gebuehr_erlassbar(ma_, {"status": "1000"}) == (True, "ok")
    assert m.gebuehr_erlassbar(ma_, {"status": "200"})[0] is False      # Rechnung noch offen -> Mahnung bleibt
    assert m.gebuehr_erlassbar({**ma_, "status": "100"}, {"status": "1000"})[0] is False   # Entwurf nicht
