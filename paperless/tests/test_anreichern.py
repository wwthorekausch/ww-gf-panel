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


def test_belegnummer_im_dateinamen_mit_unterstrich():
    belege = [{"id": "11", "nr": "201020737315", "firma": "plentymarkets", "brutto": Decimal("1"), "netto": Decimal("1")}]
    doc = {"title": "invoice", "original_file_name": "invoice_201020737315_2026-09-28.pdf", "content": ""}
    assert a.finde_beleg(doc, belege)["id"] == "11"


def test_belegnummer_kein_teiltreffer_ziffern():
    belege = [{"id": "11", "nr": "20102073731", "firma": "x", "brutto": Decimal("1"), "netto": Decimal("1")}]
    assert a.finde_beleg({"title": "", "original_file_name": "invoice_201020737315.pdf", "content": ""}, belege) is None


def test_gleiche_nummer_mehrfach_nimmt_gebuchten():
    belege = [{"id": "20", "nr": "MP29716", "status": 50, "firma": "p", "brutto": Decimal("1"), "netto": Decimal("1")},
              {"id": "10", "nr": "MP29716", "status": 1000, "firma": "p", "brutto": Decimal("1"), "netto": Decimal("1")}]
    assert a.finde_beleg({"title": "", "original_file_name": "invoice_MP29716_2026-09-30.pdf", "content": ""}, belege)["id"] == "10"


def test_verschiedene_nummern_bleibt_mehrdeutig():
    belege = [{"id": "1", "nr": "AAAA11", "status": 1000, "firma": "p", "brutto": Decimal("1"), "netto": Decimal("1")},
              {"id": "2", "nr": "BBBB22", "status": 1000, "firma": "p", "brutto": Decimal("1"), "netto": Decimal("1")}]
    assert a.finde_beleg({"title": "", "original_file_name": "AAAA11 BBBB22", "content": ""}, belege) is None


def test_belegnummer_ohne_ziffer_zaehlt_nicht():
    belege = [{"id": "1", "nr": "5673330964", "status": 50, "firma": "Google", "brutto": Decimal("1"), "netto": Decimal("1")},
              {"id": "2", "nr": "Gebühren", "status": 1000, "firma": "Bank", "brutto": Decimal("1"), "netto": Decimal("1")}]
    doc = {"title": "5673330964", "original_file_name": "5673330964.pdf", "content": "Rechnungsnummer 5673330964 Gebühren"}
    assert a.finde_beleg(doc, belege)["id"] == "1"


def test_nummer_im_dateinamen_geht_vor_text():
    belege = [{"id": "1", "nr": "201020737315", "status": 1000, "firma": "p", "brutto": Decimal("1"), "netto": Decimal("1")},
              {"id": "2", "nr": "1293330", "status": 1000, "firma": "x", "brutto": Decimal("1"), "netto": Decimal("1")}]
    doc = {"title": "invoice", "original_file_name": "invoice_201020737315_2026-09-28.pdf",
           "content": "Invoice 201020737315 Order ID 1293330"}
    assert a.finde_beleg(doc, belege)["id"] == "1"


# --- Korrekturen nach Live-Befund ---
def test_textnummer_braucht_betrag_postleitzahl_trifft_nicht():
    belege = [{"id": "129585933", "nr": "24114", "status": 1000, "firma": "Vicci", "brutto": Decimal("89.48"), "netto": Decimal("83.63")}]
    doc = {"title": "160202127", "original_file_name": "160202127.pdf",
           "content": "DigitalOcean Deliusstraße 7 Kiel 24114 GERMANY Payment -$66.40"}
    assert a.finde_beleg(doc, belege) is None


def test_textnummer_mit_betrag_trifft():
    belege = [{"id": "1", "nr": "24114", "status": 1000, "firma": "Vicci", "brutto": Decimal("89.48"), "netto": Decimal("83.63")}]
    doc = {"title": "x", "original_file_name": "y.pdf", "content": "Rechnung 24114 Gesamt 89,48 EUR"}
    assert a.finde_beleg(doc, belege)["id"] == "1"


def test_betrag_im_text_formate():
    assert a.betrag_im_text(Decimal("1234.5"), "Summe 1.234,50 €")
    assert a.betrag_im_text(Decimal("66.4"), "Total $66.40")
    assert not a.betrag_im_text(Decimal("89.48"), "Total 66,40")


def test_netto_gleich_brutto_aus_text_korrigiert():
    text = "Summe Betrag 136,63 € +19 % USt. auf 136,63 € Gesamt 162,59 €"
    assert a.netto_pruefen(Decimal("162.59"), Decimal("162.59"), text) == Decimal("136.63")


def test_netto_gleich_brutto_ohne_beleg_im_text_leer():
    assert a.netto_pruefen(Decimal("162.59"), Decimal("162.59"), "keine Angaben") is None


def test_netto_verschieden_bleibt():
    assert a.netto_pruefen(Decimal("119"), Decimal("100"), "") == Decimal("100")


def test_korrektur_ueberschreibt_und_leert_nach_quelle():
    doc = {"id": 181, "custom_fields": [{"field": 1, "value": "24114"}, {"field": 3, "value": "Vicci"}, {"field": 4, "value": "K9"},
                                        {"field": 5, "value": "129585933"}],
           "correspondent": 5, "storage_path": 1}
    body = a.korrektur(doc, None, CF, OPT, korrespondent_id=None)
    werte = {f["field"]: f["value"] for f in body["custom_fields"]}
    assert werte[1] is None and werte[3] is None and werte[4] == "K9"   # Kundennummer: nicht von Quelle abhängig -> bleibt
    assert body["correspondent"] is None


def test_korrektur_keine_aenderung_none():
    doc = {"id": 1, "custom_fields": [{"field": 1, "value": "RE-1"}], "correspondent": 3, "storage_path": 1}
    assert a.korrektur(doc, a.Quelle(nummer="RE-1"), CF, OPT, korrespondent_id=3) is None


def test_aehnlicher_korrespondent():
    assert a.aehnlich("Kostal", "KOSTAL Industrie Elektrik GmbH & Co. KG")
    assert a.aehnlich("PlentyONE GmbH", "plentymarkets") and a.aehnlich("PlentyONE GmbH", "plentysystems AG")
    assert not a.aehnlich("Vicci Caffe Rösterei GmbH", "DigitalOcean")


def test_korrektur_behaelt_aehnlichen_korrespondenten():
    doc = {"id": 1, "custom_fields": [], "correspondent": 3, "storage_path": 1}
    ks = {3: "Kostal"}
    body = a.korrektur(doc, a.Quelle(firma="KOSTAL Industrie Elektrik GmbH & Co. KG"), CF, OPT,
                       korrespondent_id=None, korrespondent_namen=ks)
    assert "correspondent" not in body


def test_re_nummer_mit_unterstrich():
    assert a.re_nummer({"title": "2026-05-07_Rechnung_RE-27242_f3651267", "original_file_name": "", "content": "RE-1 RE-2"}) == "RE-27242"


def test_ohne_quelle_nur_leeren_wenn_sevdesk_id_gesetzt():
    doc = {"id": 95, "custom_fields": [{"field": 1, "value": "RE-27242"}, {"field": 3, "value": "Hood"}], "correspondent": 5, "storage_path": 1}
    assert a.korrektur(doc, None, CF, OPT, korrespondent_id=None) is None


def test_platzhalter_firma_wird_nicht_eingetragen():
    doc = {"id": 1, "custom_fields": [], "correspondent": None, "storage_path": 1}
    body = a.plan(doc, a.Quelle(nummer="11811331", firma="- keine Angabe -"), CF, OPT, None, 1)
    assert {f["field"]: f["value"] for f in body["custom_fields"]} == {1: "11811331"}


# --- Stufe 2: Firma + Betrag + Datum aus OCR; Zahlungsbelege ---
from datetime import date

DO = {"id": "GMI-1", "nr": "556820130", "firma": "DigitalOcean", "brutto": Decimal("66.4"), "netto": Decimal("66.4"),
      "datum": date(2026, 10, 1), "status": 0}
RECEIPT = {"title": "160202127", "original_file_name": "160202127.pdf", "created": "2026-10-01",
           "content": "Payment Receipt From DigitalOcean LLC ID: 160202127 Kiel 24114 Payment (Amex ending in 1007): -$66.40"}


def test_stufe2_firma_betrag_datum():
    assert a.finde_ueber_firma_betrag(RECEIPT, [DO])["nr"] == "556820130"


def test_stufe2_betrag_falsch():
    assert a.finde_ueber_firma_betrag(RECEIPT, [{**DO, "brutto": Decimal("97.22")}]) is None


def test_stufe2_datum_zu_weit():
    assert a.finde_ueber_firma_betrag(RECEIPT, [{**DO, "datum": date(2026, 9, 10)}]) is None


def test_stufe2_zwei_kandidaten_mehrdeutig():
    assert a.finde_ueber_firma_betrag(RECEIPT, [DO, {**DO, "id": "GMI-2", "nr": "999999999"}]) is None


def test_stufe2_kurzer_firmenname_zaehlt_nicht():
    assert a.finde_ueber_firma_betrag({**RECEIPT, "content": "Bank 66,40"}, [{**DO, "firma": "Bank"}]) is None


def test_zahlungsbeleg_erkennen():
    assert a.ist_zahlungsbeleg(RECEIPT)
    assert a.ist_zahlungsbeleg({"title": "Zahlungsbestätigung", "original_file_name": "", "content": ""})
    assert not a.ist_zahlungsbeleg({"title": "Rechnung 4711", "original_file_name": "", "content": "Rechnung Betrag 10 EUR"})


def test_quellwechsel_leert_veraltete_werte():
    doc = {"id": 181, "custom_fields": [{"field": 1, "value": "24114"}, {"field": 5, "value": "129585933"},
                                        {"field": 7, "value": "EUR83.63"}], "correspondent": None, "storage_path": 1}
    q = a.Quelle(nummer="556820130", brutto=Decimal("66.4"), firma="DigitalOcean", waehrung="USD")
    werte = {f["field"]: f["value"] for f in a.korrektur(doc, q, CF, OPT, korrespondent_id=None)["custom_fields"]}
    assert werte[1] == "556820130" and werte[5] is None and werte[7] is None and werte[6] == "USD66.40"


def test_geld_waehrung():
    assert a.geld(Decimal("66.4"), "USD") == "USD66.40" and a.geld(Decimal("1")) == "EUR1.00"


def test_korrespondent_ohne_leerzeichen_gleich():
    assert a.korrespondent_id("DigitalOcean", [{"id": 11, "name": "Digital Ocean"}]) == 11


def test_firma_fuer_sevdesk_ocr_weicht_ab():
    doc = {"custom_fields": [{"field": 3, "value": "welltec GmbH"}]}
    assert a.firma_fuer_sevdesk(doc, a.Quelle(firma="Holstein Kiel", sevdesk_id="9"), CF) == "welltec GmbH"


def test_firma_fuer_sevdesk_aehnlich_oder_ohne_beleg_none():
    doc = {"custom_fields": [{"field": 3, "value": "PlentyONE GmbH"}]}
    assert a.firma_fuer_sevdesk(doc, a.Quelle(firma="plentymarkets", sevdesk_id="9"), CF) is None
    doc = {"custom_fields": [{"field": 3, "value": "welltec GmbH"}]}
    assert a.firma_fuer_sevdesk(doc, a.Quelle(firma="Holstein Kiel"), CF) is None
    assert a.firma_fuer_sevdesk({"custom_fields": []}, a.Quelle(firma="Holstein Kiel", sevdesk_id="9"), CF) is None
