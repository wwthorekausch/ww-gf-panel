import sqlite3
from datetime import date

import pytest

import actions
import db
from conftest import D
from modell import Beleg, Fall, Position, Rechnung, Standardregel, Umsatz


class FakeClient:
    def __init__(self, nachlesen_status=100, nachlesen_brutto="49.99", nachlesen_kat="2819", fehler_bei=None):
        self.calls = []
        self.v = {"status": str(nachlesen_status), "sumGross": nachlesen_brutto, "currency": "EUR"}
        self.kat = nachlesen_kat
        self.fehler_bei = fehler_bei

    def get(self, path, params=None):
        self.calls.append(("GET", path))
        if path.startswith("Voucher/"):
            return {"objects": [self.v]}
        return {"objects": [{"accountingType": {"id": self.kat}}]}

    def _write(self, method, path, json):
        self.calls.append((method, path))
        if self.fehler_bei and self.fehler_bei in path:
            raise RuntimeError("HTTP 400")
        return {"objects": {"voucher": {"id": 999}}}

    def post(self, path, json=None):
        return self._write("POST", path, json)

    def put(self, path, json=None):
        return self._write("PUT", path, json)

    def delete(self, path, json=None):
        return self._write("DELETE", path, json)


def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    db.init(c)
    return c


def schreiber(client, dry_run=False, limit=20):
    c = conn()
    return actions.Schreiber(client, c, db.run_start(c, dry_run), dry_run, limit), c


U = Umsatz("77", "1001", date(2026, 9, 10), D("-49.99"), "HETZNER", "R123")
POS = (Position("11", "2819", D("19"), D("49.99")),)


def beleg(status=50, datum=date(2026, 9, 8), positionen=POS):
    return Beleg("5", datum, "Hetzner", D("49.99"), None, "EUR", status, "default", positionen,
                 roh={"id": "5", "objectName": "Voucher", "voucherDate": "2026-09-08", "supplierName": "Hetzner",
                      "creditDebit": "C", "taxType": "default", "voucherType": "VOU", "currency": "EUR"})


def fall_beleg(**kw):
    return Fall("beleg", True, "sicher", date(2026, 9, 8), umsatz=U, beleg=kw.pop("b", beleg()), **kw)


def schreibpfade(client):
    return [(m, p) for m, p in client.calls if m != "GET"]


def test_dry_run_schreibt_nie():
    c = FakeClient()
    s, conn_ = schreiber(c, dry_run=True)
    s.ausfuehren(fall_beleg())
    assert schreibpfade(c) == []
    assert [r["ergebnis"] for r in conn_.execute("SELECT ergebnis FROM actions")] == ["dry-run", "dry-run"]


def test_entwurf_reihenfolge_speichern_nachlesen_zuordnen():
    c = FakeClient()
    s, _ = schreiber(c)
    assert s.ausfuehren(fall_beleg()) == "ok"
    assert c.calls == [("POST", "Voucher/Factory/saveVoucher"), ("GET", "Voucher/5"), ("GET", "VoucherPos"),
                       ("PUT", "Voucher/5/bookAmount")]
    assert s.zaehler == 1


def test_offener_beleg_ohne_korrektur_nur_zuordnen():
    c = FakeClient()
    s, _ = schreiber(c)
    s.ausfuehren(fall_beleg(b=beleg(status=100)))
    assert schreibpfade(c) == [("PUT", "Voucher/5/bookAmount")]


def test_nachlesen_abweichend_kein_zuordnen():
    c = FakeClient(nachlesen_brutto="48.00")
    s, _ = schreiber(c)
    with pytest.raises(actions.Abbruch, match="Nachlesen"):
        s.ausfuehren(fall_beleg(korrektur={"brutto_eur": D("49.99")}))
    assert ("PUT", "Voucher/5/bookAmount") not in c.calls


def test_fehler_beim_speichern_kein_zuordnen():
    c = FakeClient(fehler_bei="saveVoucher")
    s, conn_ = schreiber(c)
    with pytest.raises(actions.Abbruch):
        s.ausfuehren(fall_beleg())
    assert ("PUT", "Voucher/5/bookAmount") not in c.calls
    assert conn_.execute("SELECT ergebnis FROM actions").fetchone()["ergebnis"] == "fehler"


def test_guard_datum_vor_stichtag():
    s, _ = schreiber(FakeClient())
    with pytest.raises(actions.RegelVerletzung):
        s.ausfuehren(fall_beleg(b=beleg(datum=date(2024, 12, 31))))


def test_guard_pfad_whitelist():
    s, _ = schreiber(FakeClient())
    for pfad in ("Invoice/1/changeStatus", "Invoice/1", "Voucher/5", "CheckAccountTransaction/77"):
        with pytest.raises(actions.RegelVerletzung):
            s._schreibe("put", pfad, {}, "X", "1", "test")


def test_korrektur_bei_mehreren_positionen_abbruch():
    pos = (Position("11", "2819", D("19"), D("20")), Position("12", "2819", D("19"), D("29.99")))
    s, _ = schreiber(FakeClient())
    with pytest.raises(actions.Abbruch, match="Position"):
        s.ausfuehren(fall_beleg(b=beleg(positionen=pos), korrektur={"kategorie_id": "2819"}))


def test_limit_stoppt_vor_schreiben():
    c = FakeClient()
    s, _ = schreiber(c, limit=1)
    s.ausfuehren(fall_beleg())
    n = len(c.calls)
    with pytest.raises(actions.LimitErreicht):
        s.ausfuehren(fall_beleg())
    assert len(c.calls) == n


def test_rechnung_nur_bookamount():
    c = FakeClient()
    s, _ = schreiber(c)
    r = Rechnung("31", "RE-10001", date(2026, 9, 1), "RE", 200, D("1190.00"), "Beispiel Kunde")
    e = Umsatz("78", "1002", date(2026, 9, 7), D("1190.00"), "Beispiel Kunde GmbH", "RE-10001")
    s.ausfuehren(Fall("rechnung", True, "sicher", e.datum, umsatz=e, rechnung=r))
    assert c.calls == [("PUT", "Invoice/31/bookAmount")]


def test_standard_anlegen_nachlesen_zuordnen():
    c = FakeClient(nachlesen_brutto="2000", nachlesen_kat="50")
    s, _ = schreiber(c)
    u = Umsatz("79", "1001", date(2026, 9, 30), D("-2000"), "Max Mustermann", "Gehalt")
    r = Standardregel("Lohn", "Mustermann", "lohn", "50", "Max Mustermann")
    s.ausfuehren(Fall("standard", True, "Standardbuchung", u.datum, umsatz=u, regel=r))
    assert schreibpfade(c) == [("POST", "Voucher/Factory/saveVoucher"), ("PUT", "Voucher/999/bookAmount")]


def test_zuordnen_body_vorzeichen_wie_umsatz():
    # Live-Befund: Ausgabe positiv gebucht -> sevDesk paidAmount -10, Status 750. Vorzeichen = Umsatz.
    b = actions.zuordnen_body(U, D("49.99"))
    assert b["amount"] == -49.99 and b["checkAccountTransaction"] == {"id": 77, "objectName": "CheckAccountTransaction"}
    assert b["checkAccount"] == {"id": 1001, "objectName": "CheckAccount"} and b["date"] == "2026-09-10"


def test_speichern_body_usd_setzt_kurs():
    b = Beleg("5", date(2026, 9, 21), "Bitwarden", D("69.73"), D("80"), "USD", 50, "default",
              (Position("11", "2819", D("0"), D("69.73")),), roh={"id": "5", "currency": "USD"})
    body = actions.beleg_speichern_body(b, "2819", D("71.82"))
    assert body["voucher"]["status"] == 100 and body["voucher"]["propertyExchangeRate"] == "0.89775"
    assert body["voucherPosSave"][0]["sumGross"] == 71.82


# --- Final-Review-Fixes ---
class GetFehlerClient(FakeClient):
    def get(self, path, params=None):
        self.calls.append(("GET", path))
        raise RuntimeError("HTTP 500")


def test_limit_zaehlt_versuche_nicht_nur_erfolge():
    # C1: abgebrochene Fälle verbrauchen Limit
    c = FakeClient(nachlesen_brutto="1.00")
    s, _ = schreiber(c, limit=1)
    with pytest.raises(actions.Abbruch):
        s.ausfuehren(fall_beleg())
    with pytest.raises(actions.LimitErreicht):
        s.ausfuehren(fall_beleg())
    assert len(schreibpfade(c)) == 1


def test_abbruch_nach_schreiben_eigener_typ():
    # C1: Abbruch nach erfolgtem Schreibvorgang muss Lauf stoppen können
    s, _ = schreiber(FakeClient(nachlesen_brutto="1.00"))
    with pytest.raises(actions.AbbruchNachSchreiben):
        s.ausfuehren(fall_beleg())


def test_abbruch_ohne_schreiben_normaler_typ():
    s, _ = schreiber(FakeClient())
    pos = (Position("11", "2819", D("19"), D("20")), Position("12", "2819", D("19"), D("29.99")))
    with pytest.raises(actions.Abbruch) as e:
        s.ausfuehren(fall_beleg(b=beleg(positionen=pos), korrektur={"kategorie_id": "2819"}))
    assert not isinstance(e.value, actions.AbbruchNachSchreiben)


def test_nachlesen_get_fehler_wird_abbruch():
    # I5
    s, _ = schreiber(GetFehlerClient())
    with pytest.raises(actions.AbbruchNachSchreiben, match="Nachlesen"):
        s.ausfuehren(fall_beleg())


def test_standard_unerwartete_antwort_wird_abbruch():
    # I5
    class LeereAntwort(FakeClient):
        def post(self, path, json=None):
            self.calls.append(("POST", path))
            return {"objects": {}}
    s, _ = schreiber(LeereAntwort())
    u = Umsatz("79", "1001", date(2026, 9, 30), D("-12.50"), "", "Entgelt")
    r = Standardregel("Bankgebühren", "entgelt", "gebuehren", "70", "Bank")
    with pytest.raises(actions.AbbruchNachSchreiben):
        s.ausfuehren(Fall("standard", True, "Standardbuchung", u.datum, umsatz=u, regel=r))


def test_kategorie_fehlt_abbruch_vor_schreiben():
    # I5
    c = FakeClient()
    s, _ = schreiber(c)
    with pytest.raises(actions.Abbruch, match="Kategorie"):
        s.ausfuehren(fall_beleg(b=beleg(positionen=())))
    assert schreibpfade(c) == []


def test_umsatz_nur_einmal_pro_lauf():
    # I6
    c = FakeClient()
    s, _ = schreiber(c)
    s.ausfuehren(fall_beleg(b=beleg(status=100)))
    with pytest.raises(actions.Abbruch, match="bereits"):
        s.ausfuehren(fall_beleg(b=beleg(status=100)))
    assert len(schreibpfade(c)) == 1


def test_kurs_auf_6_stellen_gerundet():
    # I8
    b = Beleg("5", date(2026, 9, 21), "X", D("1.00"), D("3"), "USD", 50, "default",
              (Position("11", "2819", D("0"), D("1.00")),), roh={})
    assert actions.beleg_speichern_body(b, "2819", D("1.01"))["voucher"]["propertyExchangeRate"] == "0.336667"


def test_zuordnen_body_eingang_positiv():
    e = Umsatz("78", "1002", date(2026, 9, 7), D("1190.00"), "Kunde", "RE-10001")
    assert actions.zuordnen_body(e, D("1190.00"))["amount"] == 1190.0


# --- Duplikate löschen (eng begrenzt) ---
def nr(b, nummer="F38-0062", **kw):
    return Beleg(**{**b.__dict__, "roh": {**b.roh, "description": nummer}, **kw})


def test_duplikat_loeschen_erlaubt():
    c = FakeClient()
    s, _ = schreiber(c)
    behalten, dup = nr(beleg(), id="4"), nr(beleg())
    s.loesche_duplikat(dup, behalten)
    assert schreibpfade(c) == [("DELETE", "Voucher/5")]


def test_duplikat_loeschen_guards():
    s, _ = schreiber(FakeClient())
    behalten = nr(beleg(), id="4")
    for dup in (nr(beleg(status=100)),                    # kein Entwurf
                nr(beleg(), nummer="ANDERE"),             # andere Belegnummer
                nr(beleg(), nummer=""),                   # keine Belegnummer
                nr(beleg(), id="4"),                      # derselbe Beleg
                nr(beleg(datum=date(2024, 12, 1)))):      # vor Stichtag
        with pytest.raises(actions.RegelVerletzung):
            s.loesche_duplikat(dup, behalten)


def test_delete_nur_auf_voucher_pfad():
    s, _ = schreiber(FakeClient())
    with pytest.raises(actions.RegelVerletzung):
        s._schreibe("delete", "Invoice/5", {}, "X", "5", "test")


def test_guard_kein_speichern_fremdwaehrung():
    # Live-Befund 2026-10-01: sevDesk liest Positions-sumGross bei USD als Fremdwährung -> Beleg verfälscht
    usd = Beleg("5", date(2026, 9, 21), "Bitwarden", D("69.73"), D("80"), "USD", 50, "default",
                (Position("11", "2819", D("0"), D("69.73")),), roh={"id": "5", "currency": "USD"})
    c = FakeClient()
    s, _ = schreiber(c)
    with pytest.raises(actions.RegelVerletzung, match="Fremdwährung"):
        s.ausfuehren(fall_beleg(b=usd))
    assert schreibpfade(c) == []


# --- USD-Beleg auf EUR mit Bankbetrag umstellen ---
def usd_beleg(status=100, positionen=None):
    pos = positionen or (Position("11", "2819", D("0"), D("48.69")),)
    return Beleg("5", date(2026, 5, 21), "Bitwarden", D("48.69"), D("55.82"), "USD", status, "default", pos,
                 roh={"id": "5", "objectName": "Voucher", "currency": "USD", "voucherDate": "2026-05-21",
                      "supplierName": "Bitwarden", "creditDebit": "C", "taxType": "default", "voucherType": "VOU",
                      "propertyExchangeRate": "0.87"})


UMS_USD = Umsatz("1860067575", "1001", date(2026, 5, 21), D("-55.82"), "BITWARDEN", "x")


def test_usd_auf_eur_body():
    body = actions.usd_auf_eur_body(usd_beleg(), D("55.82"))
    assert body["voucher"]["currency"] == "EUR" and "propertyExchangeRate" not in body["voucher"]
    assert body["voucherPosSave"][0]["sumGross"] == 55.82 and body["voucherPosSave"][0]["accountingType"]["id"] == 2819


def test_usd_auf_eur_ablauf():
    c = FakeClient(nachlesen_brutto="55.82")
    s, _ = schreiber(c)
    s.usd_auf_eur(usd_beleg(), UMS_USD)
    assert schreibpfade(c) == [("POST", "Voucher/Factory/saveVoucher"), ("PUT", "Voucher/5/bookAmount")]


def test_usd_auf_eur_nachlesen_waehrung_falsch_kein_zuordnen():
    c = FakeClient(nachlesen_brutto="55.82")
    c.v["currency"] = "USD"
    s, _ = schreiber(c)
    with pytest.raises(actions.AbbruchNachSchreiben):
        s.usd_auf_eur(usd_beleg(), UMS_USD)
    assert ("PUT", "Voucher/5/bookAmount") not in c.calls


def test_usd_auf_eur_guards():
    s, _ = schreiber(FakeClient())
    eur = Beleg(**{**usd_beleg().__dict__, "waehrung": "EUR"})
    zwei = usd_beleg(positionen=(Position("11", "2819", D("0"), D("20")), Position("12", "2819", D("0"), D("28.69"))))
    bezahlt = usd_beleg(status=1000)
    eingang = Umsatz("1", "1001", date(2026, 5, 21), D("55.82"), "X", "x")
    for b, u in ((eur, UMS_USD), (zwei, UMS_USD), (bezahlt, UMS_USD), (usd_beleg(), eingang)):
        with pytest.raises(actions.RegelVerletzung):
            s.usd_auf_eur(b, u)


def test_standard_nutzt_kategorie_aus_korrektur():
    c = FakeClient(nachlesen_brutto="80", nachlesen_kat="3")
    s, _ = schreiber(c)
    u = Umsatz("80", "1001", date(2026, 6, 2), D("-80"), "Finanzamt Kiel", "UMS.ST MRZ.26")
    r = Standardregel("Finanzamt Kiel", "finanzamt", "finanzamt", "999", "Finanzamt Kiel")
    s.ausfuehren(Fall("standard", True, "Standardbuchung", u.datum, umsatz=u, regel=r, korrektur={"kategorie_id": "3"}))
    assert schreibpfade(c) == [("POST", "Voucher/Factory/saveVoucher"), ("PUT", "Voucher/999/bookAmount")]


def test_standard_eingang_als_einnahme():
    c = FakeClient(nachlesen_brutto="5000", nachlesen_kat="40")
    s, _ = schreiber(c)
    u = Umsatz("81", "1001", date(2026, 9, 1), D("5000"), "Web Wikinger GmbH", "Umbuchung", gegen_iban="DE11")
    r = Standardregel("Umbuchung eigenes Konto", "", "transit", "40", "Geldtransit")
    body = actions.neuer_beleg_body(u, r, "40")
    assert body["voucher"]["creditDebit"] == "D" and body["voucherPosSave"][0]["sumGross"] == 5000.0
    s.ausfuehren(Fall("standard", True, "Umbuchung", u.datum, umsatz=u, regel=r))
    assert schreibpfade(c) == [("POST", "Voucher/Factory/saveVoucher"), ("PUT", "Voucher/999/bookAmount")]


def test_auto_lauf_usd_mit_auf_eur():
    c = FakeClient(nachlesen_brutto="55.82")
    s, _ = schreiber(c)
    f = Fall("beleg", True, "sicher", date(2026, 5, 21), umsatz=UMS_USD, beleg=usd_beleg(), korrektur={"auf_eur": D("55.82")})
    s.ausfuehren(f)
    assert schreibpfade(c) == [("POST", "Voucher/Factory/saveVoucher"), ("PUT", "Voucher/5/bookAmount")]


def test_auto_lauf_usd_mit_kategoriekorrektur():
    c = FakeClient(nachlesen_brutto="55.82", nachlesen_kat="2820")
    s, _ = schreiber(c)
    f = Fall("beleg", True, "sicher", date(2026, 5, 21), umsatz=UMS_USD, beleg=usd_beleg(),
             korrektur={"auf_eur": D("55.82"), "kategorie_id": "2820"})
    s.ausfuehren(f)
    body = c.bodies[0] if hasattr(c, "bodies") else None
    assert schreibpfade(c)[-1] == ("PUT", "Voucher/5/bookAmount")


# --- GMI-Beleg hochladen ---
class FakeGmi:
    def __init__(self, tags=None):
        self.calls, self.tags = [], tags or ["Software"]

    def datei(self, uid):
        self.calls.append(("GET", f"documents/{uid}/file"))
        return b"%PDF-1.4 test"

    def dokument(self, uid):
        self.calls.append(("GET", f"documents/{uid}"))
        return {"meta_data": {"tags": list(self.tags)}}

    def put(self, path, json=None):
        self.calls.append(("PUT", path, json))
        return {"success": True}


class UploadClient(FakeClient):
    def upload(self, path, dateiname, inhalt):
        self.calls.append(("UPLOAD", path))
        return {"objects": {"filename": "tmp123.pdf"}}

    def get(self, path, params=None):
        r = super().get(path, params)
        if path.startswith("Voucher/"):
            r["objects"][0]["document"] = {"id": "9"}
        return r


def plan_fall():
    import gmi
    d = gmi.parse_dok({"documentUid": 77, "companyName": "Beispiel Hosting GmbH", "documentNumber": "R-1001",
                       "documentDate": "2026-09-01", "grossAmount": 49.99, "currency": "EUR", "tags": ["Software"]})
    plan = gmi.UploadPlan(True, "sicher", "2819", "default", D("19"), D("49.99"))
    return d, U, plan


def test_gmi_hochladen_ablauf_und_tag():
    c, g = UploadClient(), FakeGmi()
    s, _ = schreiber(c)
    s.gmi = g
    d, u, plan = plan_fall()
    s.gmi_hochladen(d, u, plan)
    assert schreibpfade(c) == [("UPLOAD", "Voucher/Factory/uploadTempFile"), ("POST", "Voucher/Factory/saveVoucher"),
                               ("PUT", "Voucher/999/bookAmount")]
    assert g.calls[-1] == ("PUT", "documents/77", {"tags": ["Software", "Sevdesk"]})
    assert ("GET", "documents/77") not in g.calls     # Tags kommen aus der Dokumentliste, kein Extra-Call


def test_gmi_hochladen_dry_run_schreibt_nichts():
    c, g = UploadClient(), FakeGmi()
    s, _ = schreiber(c, dry_run=True)
    s.gmi = g
    s.gmi_hochladen(*plan_fall())
    assert schreibpfade(c) == [] and not any(x[0] == "PUT" for x in g.calls)


def test_gmi_hochladen_nicht_sicher_verweigert():
    c, g = UploadClient(), FakeGmi()
    s, _ = schreiber(c)
    s.gmi = g
    d, u, plan = plan_fall()
    with pytest.raises(actions.RegelVerletzung):
        s.gmi_hochladen(d, u, plan._replace(sicher=False))
    assert schreibpfade(c) == []


def test_gmi_tag_pfad_nur_tags():
    s, _ = schreiber(UploadClient())
    s.gmi = FakeGmi()
    with pytest.raises(actions.RegelVerletzung):
        s._gmi_schreibe("documents/77", {"tags": ["x"], "grossAmount": "1"})


def test_gmi_regelverletzung_wird_nicht_abgeschwaecht(monkeypatch):
    c, g = UploadClient(), FakeGmi()
    s, _ = schreiber(c)
    s.gmi = g
    def boom(*a, **k):
        raise actions.RegelVerletzung("x")
    monkeypatch.setattr(s, "_gmi_schreibe", boom)
    with pytest.raises(actions.RegelVerletzung):
        s.gmi_hochladen(*plan_fall())


def test_gmi_dry_run_laedt_kein_pdf():
    c, g = UploadClient(), FakeGmi()
    s, _ = schreiber(c, dry_run=True)
    s.gmi = g
    s.gmi_hochladen(*plan_fall())
    assert ("GET", "documents/77/file") not in g.calls


def test_gmi_beschreibung_ohne_nummer():
    import gmi
    d = gmi.parse_dok({"documentUid": 5, "companyName": "REWE", "documentNumber": "", "documentDate": "2026-05-28",
                       "grossAmount": 8.56, "currency": "EUR"})
    plan = gmi.UploadPlan(True, "sicher", "72", "default", D("7"), D("8.56"))
    assert actions.gmi_beleg_body(d, U, plan, "t.pdf")["voucher"]["description"] == "GMI-5"


def test_gmi_taggen_nur_tag():
    c, g = UploadClient(), FakeGmi()
    s, _ = schreiber(c)
    s.gmi = g
    d, _, _ = plan_fall()
    s.gmi_taggen(d)
    assert schreibpfade(c) == [] and g.calls == [("PUT", "documents/77", {"tags": ["Software", "Sevdesk"]})]


def test_gmi_taggen_vor_stichtag_verweigert():
    import gmi
    d = gmi.parse_dok({"documentUid": 1, "companyName": "X", "documentDate": "2024-12-31", "grossAmount": 1})
    s, _ = schreiber(UploadClient())
    s.gmi = FakeGmi()
    with pytest.raises(actions.RegelVerletzung):
        s.gmi_taggen(d)
