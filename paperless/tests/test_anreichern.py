from decimal import Decimal

import anreichern as a

CF = {"Brutto": 6, "Firma": 3, "Kundenummer": 4, "Netto": 7, "Rechnungsnummer": 1, "Rechnungstyp": 8, "SevdeskID": 5, "Zahlart": 2}
OPT = {"Rechnungstyp": {"Rechnung": "r1", "Gutschrift": "g1", "Stornorechnung": "s1"},
       "Zahlart": {"Kreditkarte": "k1", "Lastschrift": "l1", "Paypal": "p1", "Rechnung": "re1"}}


def test_re_nummer_eindeutig_bevorzugt_titel():
    d = {"title": "RE-27242", "original_file_name": "x.pdf", "content": "Storno zu RE-27100 ... RE-27242"}
    assert a.re_nummer(d) == "RE-27242"


def test_re_nummer_mehrdeutig_none():
    assert a.re_nummer({"title": "x", "original_file_name": "y", "content": "RE-1001 und RE-1002"}) is None


def test_geld_format():
    assert a.geld(Decimal("49.9")) == "EUR49.90"


def test_plan_nur_leere_felder_und_bestand_bleibt():
    doc = {"id": 1, "custom_fields": [{"field": 1, "value": "ALT-1"}, {"field": 6, "value": None}],
           "correspondent": None, "storage_path": None}
    quelle = a.Quelle(nummer="RE-1", brutto=Decimal("119"), netto=Decimal("100"), firma="Kunde A", kundennummer="K1",
                      sevdesk_id="55", rechnungstyp="Rechnung", zahlart=None)
    body = a.plan(doc, quelle, CF, OPT, korrespondent_id=9, speicherpfad_id=1)
    werte = {f["field"]: f["value"] for f in body["custom_fields"]}
    assert werte[1] == "ALT-1"                    # vorhandener Wert nie überschrieben
    assert werte[6] == "EUR119.00" and werte[7] == "EUR100.00" and werte[3] == "Kunde A" and werte[4] == "K1"
    assert werte[5] == "55" and werte[8] == "r1" and 2 not in werte
    assert body["correspondent"] == 9 and body["storage_path"] == 1


def test_plan_nichts_zu_tun():
    doc = {"id": 1, "custom_fields": [{"field": 1, "value": "RE-1"}], "correspondent": 3, "storage_path": 1}
    assert a.plan(doc, a.Quelle(nummer="RE-1"), CF, OPT, korrespondent_id=9, speicherpfad_id=1) is None


def test_plan_ohne_quelle_nur_speicherpfad():
    doc = {"id": 1, "custom_fields": [], "correspondent": None, "storage_path": None}
    assert a.plan(doc, None, CF, OPT, korrespondent_id=None, speicherpfad_id=1) == {"storage_path": 1}


def test_eingang_belegnummer_im_text():
    belege = [{"id": "11", "nr": "INV-77001", "firma": "Beispiel Hosting", "brutto": Decimal("10"), "netto": Decimal("8.4")}]
    doc = {"title": "Receipt", "original_file_name": "r.pdf", "content": "Invoice INV-77001 total 10.00"}
    assert a.finde_beleg(doc, belege)["id"] == "11"


def test_eingang_kurze_nummer_kein_treffer():
    belege = [{"id": "11", "nr": "123", "firma": "X", "brutto": Decimal("1"), "netto": Decimal("1")}]
    assert a.finde_beleg({"title": "", "original_file_name": "", "content": "Nr 123"}, belege) is None


def test_korrespondent_finden_normalisiert():
    ks = [{"id": 10, "name": "PlentyONE GmbH"}]
    assert a.korrespondent_id("plentyone gmbh", ks) == 10 and a.korrespondent_id("Neu AG", ks) is None


def test_zahlart_aus_gmi():
    assert a.zahlart("cc") == "Kreditkarte" and a.zahlart("direct_debit") == "Lastschrift" and a.zahlart("x") is None


def test_platzhalter_nie_korrespondent():
    for name in ("- keine Angabe -", "Sonstiges", "", "  "):
        assert not a.korrespondent_tauglich(name)
    assert a.korrespondent_tauglich("Hetzner")
