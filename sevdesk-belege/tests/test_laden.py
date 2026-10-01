from datetime import date

import laden
from conftest import D


class FakeGet:
    def __init__(self, seiten):
        self.seiten = seiten
        self.aufrufe = []

    def get(self, path, params=None):
        self.aufrufe.append((path, dict(params or {})))
        return {"objects": self.seiten.pop(0)}


def test_alle_paginiert():
    c = FakeGet([[{"id": i} for i in range(1000)], [{"id": "x"}]])
    assert len(laden.alle(c, "Voucher", {"status": 50})) == 1001
    assert c.aufrufe[1][1] == {"status": 50, "limit": 1000, "offset": 1000}


def test_parse_umsatz():
    u = laden.parse_umsatz({"id": 7, "checkAccount": {"id": "1001"}, "valueDate": "2026-09-07T00:00:00+02:00",
                            "amount": "-1500.0", "payeePayerName": None, "paymtPurpose": "STEUERNR"})
    assert (u.id, u.konto_id, u.datum, u.betrag, u.name, u.zweck) == ("7", "1001", date(2026, 9, 7), D("-1500.0"), "", "STEUERNR")


def test_parse_beleg_usd_und_position():
    p = laden.parse_position({"id": "11", "accountingType": {"id": "2819"}, "taxRate": "0", "sumGross": "69.73"})
    b = laden.parse_beleg({"id": "5", "voucherDate": "2026-09-21T00:00:00+02:00", "supplierName": "Bitwarden",
                           "sumGross": "69.73", "sumGrossForeignCurrency": "80", "currency": "USD", "status": "50",
                           "taxType": "default", "document": {"id": "9"}}, [p])
    assert b.waehrung == "USD" and b.brutto_fremd == D("80") and b.status == 50
    assert b.kategorie_id == "2819" and b.steuer == "default:0" and b.hat_dokument


def test_parse_beleg_ohne_dokument_lieferant_aus_supplier():
    b = laden.parse_beleg({"id": "6", "voucherDate": None, "supplier": {"name": "TK"}, "sumGross": "1",
                           "currency": None, "status": "1000", "taxType": "default", "document": None}, [])
    assert b.lieferant == "TK" and b.datum is None and b.waehrung == "EUR" and not b.hat_dokument


def test_parse_rechnung_offener_betrag():
    r = laden.parse_rechnung({"id": "1", "invoiceNumber": "RE-1", "invoiceDate": "2026-09-01T00:00:00+02:00",
                              "invoiceType": "RE", "status": "750", "sumGross": "100", "paidAmount": "40",
                              "contact": {"name": "Kunde A"}})
    assert r.offen == D("60") and r.status == 750 and r.kunde == "Kunde A"


def test_parse_umsatz_gegen_iban():
    u = laden.parse_umsatz({"id": 1, "checkAccount": {"id": "1"}, "valueDate": "2026-09-01", "amount": "5",
                            "payeePayerAcctNo": "de11 2022 0800", "payeePayerName": "X", "paymtPurpose": ""})
    assert u.gegen_iban == "DE1120220800"
