from datetime import date, timedelta
from decimal import Decimal

import rules
from conftest import HEUTE, D
from modell import Beleg, Grenzen, Position, Rechnung, Standardregel, Umsatz

G = Grenzen()


def umsatz(id="u1", datum=date(2026, 9, 10), betrag="-49.99", name="Hetzner Online GmbH", zweck="Rechnung R123", konto="1"):
    return Umsatz(id=id, konto_id=konto, datum=datum, betrag=D(betrag), name=name, zweck=zweck)


def beleg(id="b1", datum=date(2026, 9, 8), lieferant="Hetzner Online GmbH", brutto="49.99", fremd=None,
          waehrung="EUR", status=50, steuerart="default", kat="2819", satz="19", positionen=None, dok=True):
    pos = positionen if positionen is not None else (Position(id=f"p{id}", kategorie_id=kat, steuersatz=D(satz), brutto=D(brutto)),)
    return Beleg(id=id, datum=datum, lieferant=lieferant, brutto_eur=D(brutto),
                 brutto_fremd=D(fremd) if fremd else None, waehrung=waehrung, status=status,
                 steuerart=steuerart, positionen=pos, hat_dokument=dok)


def historie(lieferant="Hetzner Online GmbH", kat="2819", satz="19", n=2, brutto="49.99", dok=True, start=date(2025, 3, 1)):
    return [beleg(id=f"h{lieferant}{i}", datum=start + timedelta(days=30 * i), lieferant=lieferant,
                  kat=kat, satz=satz, brutto=brutto, status=1000, dok=dok) for i in range(n)]


def test_norm_entfernt_rechtsform_und_sonderzeichen():
    assert rules.norm("Hetzner Online GmbH & Co. KG") == "hetzner online"


def test_name_passt_unscharf():
    assert rules.name_passt("Hetzner Online GmbH", umsatz(name="HETZNER ONLINE"))
    assert rules.name_passt("Bitwarden Inc.", umsatz(name="", zweck="PAYPAL *BITWARDEN 4029357733"))
    assert not rules.name_passt("Hetzner Online GmbH", umsatz(name="Google Ireland", zweck="Workspace"))


def test_name_passt_kurze_tokens_zaehlen_nicht():
    assert not rules.name_passt("A&O", umsatz(name="A und O Hotels"))


def test_ab_stichtag_filtert_und_sortiert_neu_nach_alt():
    alt = umsatz(id="alt", datum=date(2024, 12, 31))
    a = umsatz(id="a", datum=date(2025, 1, 1))
    b = umsatz(id="b", datum=date(2026, 9, 1))
    zukunft = umsatz(id="z", datum=date(2030, 7, 26))
    assert [x.id for x in rules.ab_stichtag([a, alt, zukunft, b], HEUTE)] == ["b", "a"]


def test_ab_stichtag_ohne_datum_raus():
    assert rules.ab_stichtag([beleg(datum=None)], HEUTE) == []


def test_duplikate_gleicher_lieferant_betrag_datum():
    b1, b2, b3 = beleg(id="1"), beleg(id="2"), beleg(id="3", brutto="10")
    assert rules.duplikate([b1, b2, b3]) == {"1", "2"}


def test_lerne_eindeutig():
    w = rules.lerne(historie(), G)
    assert w["hetzner online"].kategorie_id == "2819"
    assert w["hetzner online"].steuer == "default:19"


def test_lerne_zu_wenig_historie():
    assert rules.lerne(historie(n=1), G) == {}


def test_lerne_ausreisser_kategorie_kein_wissen():
    h = historie(n=2) + historie(kat="9999", n=1, start=date(2026, 1, 5))
    assert "hetzner online" not in rules.lerne(h, G)


def test_lerne_ignoriert_vor_stichtag():
    assert rules.lerne(historie(start=date(2024, 1, 1), n=2), G) == {}


def test_lerne_letzter_betrag():
    h = historie(n=1, brutto="100") + historie(n=1, brutto="110", start=date(2026, 8, 1))
    assert rules.lerne(h, G)["hetzner online"].letzter_betrag == D("110")


# --- Task 3: Beleg <-> Zahlung ---
from collections import Counter

from modell import Fall

W = rules.lerne(historie(), G)


def bewerte(b, us=None, wissen=W, dup=frozenset(), g=G):
    us = us if us is not None else [umsatz()]
    kand = rules.kandidaten_beleg(b, us, g)
    return rules.bewerte_beleg(b, kand, Counter(u.id for u in kand), wissen, set(dup), g, HEUTE)


def test_beleg_sicher_eur():
    f = bewerte(beleg())
    assert f.sicher and f.umsatz.id == "u1" and f.korrektur == {}


def test_beleg_betrag_cent_abweichung_kein_kandidat():
    f = bewerte(beleg(brutto="50.00"))
    assert not f.sicher and f.grund == "keine passende Zahlung"


def test_beleg_zeitfenster():
    assert bewerte(beleg(datum=date(2026, 9, 15))).sicher          # Zahlung 5 Tage vorher
    assert not bewerte(beleg(datum=date(2026, 9, 16))).sicher      # 6 Tage vorher
    assert bewerte(beleg(datum=date(2026, 7, 27))).sicher          # 45 Tage nachher
    assert not bewerte(beleg(datum=date(2026, 7, 26))).sicher      # 46 Tage nachher


def test_beleg_zwei_kandidaten_review():
    f = bewerte(beleg(), [umsatz(id="u1"), umsatz(id="u2", datum=date(2026, 9, 12))])
    assert not f.sicher and "2 mögliche Zahlungen" in f.grund


def test_beleg_umsatz_passt_zu_mehreren_belegen():
    b = beleg()
    u = umsatz()
    f = rules.bewerte_beleg(b, [u], Counter({u.id: 2}), W, set(), G, HEUTE)
    assert not f.sicher and f.grund == "Zahlung passt zu mehreren Belegen"


def test_beleg_duplikat_review():
    f = bewerte(beleg(), dup={"b1"})
    assert not f.sicher and f.grund == "mögliches Duplikat"


def test_beleg_datum_zukunft_review():
    f = bewerte(beleg(datum=date(2030, 7, 26)))
    assert not f.sicher and "Zukunft" in f.grund


def test_beleg_name_passt_nicht():
    f = bewerte(beleg(), [umsatz(name="Google Ireland", zweck="x")])
    assert not f.sicher and f.grund == "Lieferant nicht im Zahlungstext"


def test_beleg_ueber_max_betrag():
    h = rules.lerne(historie(brutto="2500"), G)
    f = bewerte(beleg(brutto="2500"), [umsatz(betrag="-2500")], wissen=h)
    assert not f.sicher and "Betrag über" in f.grund


def test_beleg_unbekannter_lieferant():
    f = bewerte(beleg(), wissen={})
    assert not f.sicher and f.grund == "Lieferant ohne eindeutige Historie"


def test_beleg_steuer_abweichend():
    f = bewerte(beleg(satz="0"))
    assert not f.sicher and f.grund.startswith("Steuer")


def test_beleg_chf_review():
    f = bewerte(beleg(waehrung="CHF"))
    assert not f.sicher and f.grund == "Währung CHF"


def test_beleg_kategorie_anders_review():
    f = bewerte(beleg(kat="1111"))
    assert not f.sicher and f.grund.startswith("Kategorie")


def test_beleg_standardkategorie_wird_korrigiert():
    g = Grenzen(standard_kategorie_ids=frozenset({"1111"}))
    f = bewerte(beleg(kat="1111"), g=g)
    assert f.sicher and f.korrektur == {"kategorie_id": "2819"}


def test_beleg_korrektur_bei_mehreren_positionen_review():
    g = Grenzen(standard_kategorie_ids=frozenset({"1111"}))
    pos = (Position("p1", "1111", D("19"), D("20")), Position("p2", "1111", D("19"), D("29.99")))
    f = bewerte(beleg(positionen=pos), g=g)
    assert not f.sicher and "mehrere Positionen" in f.grund


def usd_beleg(brutto_eur):
    return beleg(lieferant="Bitwarden Inc.", brutto=brutto_eur, fremd="80", waehrung="USD", satz="0")


W_USD = rules.lerne(historie(lieferant="Bitwarden Inc.", satz="0"), G)


def test_usd_innerhalb_toleranz_wird_angepasst():
    u = umsatz(betrag="-71.82", name="BITWARDEN")        # 71.82 / 69.73 = +2.997 %
    f = bewerte(usd_beleg("69.73"), [u], wissen=W_USD)
    assert f.sicher and f.korrektur == {"auf_eur": D("71.82")}


def test_usd_ausserhalb_toleranz_kein_kandidat():
    u = umsatz(betrag="-71.83", name="BITWARDEN")        # +3.011 %
    f = bewerte(usd_beleg("69.73"), [u], wissen=W_USD)
    assert not f.sicher and f.grund == "keine passende Zahlung"


def test_usd_exakt_keine_korrektur():
    u = umsatz(betrag="-69.73", name="BITWARDEN")
    f = bewerte(usd_beleg("69.73"), [u], wissen=W_USD)
    assert f.sicher and f.korrektur == {"auf_eur": D("69.73")}


def test_eingang_ist_kein_kandidat_fuer_beleg():
    f = bewerte(beleg(), [umsatz(betrag="49.99")])
    assert f.grund == "keine passende Zahlung"


# --- Task 4: Rechnungen, Standardbuchungen, Einstufung ---
def rechnung(id="r1", nummer="RE-10001", datum=date(2026, 9, 1), typ="RE", status=200, offen="1190.00", kunde="Beispiel Kunde GmbH"):
    return Rechnung(id=id, nummer=nummer, datum=datum, typ=typ, status=status, offen=D(offen), kunde=kunde)


def eingang(**kw):
    base = dict(id="e1", datum=date(2026, 9, 7), betrag="1190.00", name="Beispiel Kunde GmbH", zweck="RE-10001")
    base.update(kw)
    return umsatz(**base)


def bewerte_r(r, us):
    k = rules.kandidaten_rechnung(r, us)
    return rules.bewerte_rechnung(r, k, Counter(u.id for u in k))


def test_rechnung_sicher():
    f = bewerte_r(rechnung(), [eingang()])
    assert f.sicher and f.art == "rechnung" and f.umsatz.id == "e1"


def test_rechnung_ohne_nummer_im_zweck_review():
    f = bewerte_r(rechnung(), [eingang(zweck="Danke")])
    assert not f.sicher and "Rechnungsnummer" in f.grund


def test_rechnung_gutschrift_storno_teilrechnung_review():
    for typ in ("GU", "SR", "TR", "ER"):
        assert not bewerte_r(rechnung(typ=typ), [eingang()]).sicher


def test_rechnung_teilbezahlt_review():
    f = bewerte_r(rechnung(status=750), [eingang()])
    assert not f.sicher and f.grund == "teilbezahlt"


def test_rechnung_zahlung_vor_rechnungsdatum_kein_kandidat():
    assert rules.kandidaten_rechnung(rechnung(datum=date(2026, 9, 8)), [eingang()]) == []


REGELN = [
    Standardregel("Lohn / Gehalt: Max Mustermann", "Max Mustermann", "lohn", "50", "Max Mustermann"),
    Standardregel("Finanzamt Kiel", "Finanzamt Kiel", "finanzamt", "60", "Finanzamt Kiel"),
    Standardregel("Bankgebühren", r"kontof(ü|ue)hrung|entgelt", "gebuehren", "70", "Bank"),
]
W_LOHN = rules.lerne(historie(lieferant="Max Mustermann", kat="50", satz="0", brutto="2000", dok=False), G)


def test_standard_lohn_innerhalb_10_prozent():
    f = rules.bewerte_standard(umsatz(betrag="-2200", name="Max Mustermann", zweck="Gehalt 09"), REGELN, W_LOHN, G)
    assert f.sicher and f.art == "standard" and f.regel.art == "lohn"


def test_standard_lohn_ueber_10_prozent_review():
    f = rules.bewerte_standard(umsatz(betrag="-2201", name="Max Mustermann", zweck="Gehalt"), REGELN, W_LOHN, G)
    assert not f.sicher and "Vormonat" in f.grund


def test_standard_lohn_ohne_historie_review():
    f = rules.bewerte_standard(umsatz(betrag="-2000", name="Max Mustermann", zweck=""), REGELN, {}, G)
    assert not f.sicher and f.grund == "kein Vormonatsbetrag"


def test_standard_finanzamt_immer_review():
    f = rules.bewerte_standard(umsatz(betrag="-50", name="Finanzamt Kiel", zweck="UST VZ 08"), REGELN, {}, G)
    assert not f.sicher and f.art == "standard" and "Finanzamt" in f.grund


def test_standard_gebuehren():
    assert rules.bewerte_standard(umsatz(betrag="-12.50", name="", zweck="Kontoführung 09/2026"), REGELN, {}, G).sicher
    assert not rules.bewerte_standard(umsatz(betrag="-100.01", name="", zweck="Entgelt"), REGELN, {}, G).sicher


def test_standard_mehrere_regeln_review():
    f = rules.bewerte_standard(umsatz(betrag="-5", name="Finanzamt Kiel", zweck="Entgelt"), REGELN, {}, G)
    assert not f.sicher and f.grund == "mehrere Standardregeln passen"


def test_ohne_beleg():
    f = rules.bewerte_standard(umsatz(name="Unbekannt AG", zweck="x"), REGELN, {}, G)
    assert f.art == "ohne_beleg" and not f.sicher


def test_umsatz_leer_kein_absturz():
    f = rules.bewerte_standard(umsatz(betrag="0", name="", zweck=""), REGELN, {}, G)
    assert f.art == "ohne_beleg"


def test_einstufen_reihenfolge_und_zuteilung():
    b = beleg()
    u_beleg = umsatz(id="u1")
    u_rech = eingang()
    u_lohn = umsatz(id="u3", datum=date(2026, 9, 30), betrag="-2000", name="Max Mustermann", zweck="Gehalt")
    u_rest = umsatz(id="u4", datum=date(2026, 9, 20), betrag="-15", name="Unbekannt", zweck="x")
    wissen = {**W, **W_LOHN}
    faelle = rules.einstufen([b], [rechnung()], [u_beleg, u_rech, u_lohn, u_rest], wissen, REGELN, G, HEUTE)
    arten = {(f.art, f.umsatz.id if f.umsatz else None) for f in faelle}
    assert arten == {("beleg", "u1"), ("rechnung", "e1"), ("standard", "u3"), ("ohne_beleg", "u4")}
    assert [f.datum for f in faelle] == sorted((f.datum for f in faelle), reverse=True)


def test_umsatz_nur_einmal_vergeben():
    # Beleg mit abweichender Steuer -> Review, beansprucht aber u3; Lohnregel darf u3 nicht zusätzlich nehmen
    b = beleg(lieferant="Max Mustermann", brutto="2000", datum=date(2026, 9, 28))
    u = umsatz(id="u3", datum=date(2026, 9, 30), betrag="-2000", name="Max Mustermann", zweck="Gehalt")
    faelle = rules.einstufen([b], [], [u], W_LOHN, REGELN, G, HEUTE)
    assert len([f for f in faelle if f.umsatz and f.umsatz.id == "u3"]) == 1
    assert faelle[0].art == "beleg"


def test_einstufen_beleg_vor_stichtag_ignoriert():
    alt = beleg(datum=date(2024, 12, 30))
    assert rules.einstufen([alt], [], [], W, [], G, HEUTE) == []


def test_baue_standardregeln_filtert_ausreisser():
    namen = {"50": "Lohn / Gehalt", "60": "bezahlte Umsatzsteuer", "70": "Kontoführung / Kartengebühren"}
    h = (historie(lieferant="Max Mustermann", kat="50", satz="0", dok=False)
         + historie(lieferant="Finanzamt Kiel", kat="60", satz="0", dok=False)
         + historie(lieferant="Beispiel Telefon GmbH", kat="60", satz="0", dok=False)   # Ausreißer: USt bei Telefonanbieter
         + historie(lieferant="Hetzner Online GmbH", kat="2819", dok=True))               # hat Dokument -> keine Regel
    regeln = rules.baue_standardregeln(h, namen, G)
    assert {(r.art, r.lieferant) for r in regeln} == {
        ("lohn", "Max Mustermann"), ("finanzamt", "Finanzamt Kiel"), ("gebuehren", "Bank")}


def test_zusammenfassung():
    f1 = Fall("beleg", True, "sicher", HEUTE, umsatz=umsatz(betrag="-10"))
    f2 = Fall("ohne_beleg", False, "kein Beleg gefunden", HEUTE, umsatz=umsatz(betrag="-5"))
    f3 = Fall("beleg", False, "keine passende Zahlung", HEUTE, beleg=beleg(brutto="7"))
    z = rules.zusammenfassung([f1, f2, f3])
    assert z == {"sicher": (1, D("10")), "review": (0, D("0")), "ohne_beleg": (1, D("5")),
                 "beleg_ohne_zahlung": (1, D("7"))}


# --- Final-Review-Fixes ---
def test_gebuehren_muster_nur_bankentgelte():
    # I2
    regel = Standardregel("Bankgebühren", rules.GEBUEHREN_MUSTER, "gebuehren", "70", "Bank")
    treffer = lambda zweck: bool(rules.passende_regeln(umsatz(name="", zweck=zweck), [regel]))
    assert treffer("ENTGELT Preis für SEPA Eingang")
    assert treffer("Kontoführung 09/2026")
    assert not treffer("Beispielprogramm Teilnahmegebuehr")
    assert not treffer("Nutzungsentgelt Plattform")
    assert not treffer("Lizenzgebühr 2026")


def test_baue_standardregeln_keine_gebuehrenregel_aus_lieferant():
    # I2: Gebühren nur über Seed-Muster, keine Regel auf Konto-/Banknamen
    namen = {"70": "Kontoführung / Kartengebühren"}
    h = historie(lieferant="Beispielbank Hauptkonto", kat="70", satz="0", dok=False)
    assert [r.name for r in rules.baue_standardregeln(h, namen, G)] == ["Bankgebühren"]


def test_beleg_vor_stichtag_beansprucht_zahlung():
    # I3: Zahlung eines Dez-2024-Belegs darf nicht als Standardbuchung sicher werden
    alt = beleg(lieferant="Max Mustermann", brutto="2000", datum=date(2024, 12, 30))
    u = umsatz(id="u9", datum=date(2025, 1, 2), betrag="-2000", name="Max Mustermann", zweck="Gehalt")
    faelle = rules.einstufen([alt], [], [u], W_LOHN, REGELN, G, HEUTE)
    assert not any(f.sicher for f in faelle)
    assert not any(f.art == "standard" for f in faelle)


def test_beleg_zukunftsdatum_erscheint_als_fall():
    # I3: OCR-Fehler (2030) muss sichtbar werden
    faelle = rules.einstufen([beleg(datum=date(2030, 7, 26))], [], [], W, [], G, HEUTE)
    assert [(f.art, f.sicher, f.grund) for f in faelle] == [("beleg", False, "Belegdatum fehlt oder in der Zukunft")]


def test_rechnungsnummer_kein_teiltreffer():
    # I4
    f = bewerte_r(rechnung(nummer="RE-100"), [eingang(zweck="RE-1001")])
    assert not f.sicher and "Rechnungsnummer" in f.grund


def test_rechnungsnummer_mit_text_drumherum():
    f = bewerte_r(rechnung(), [eingang(zweck="Zahlung der Rechnung RE-10001 vom 02.09.2026")])
    assert f.sicher


def test_review_usd_vorschlag_bankbetrag():
    # I7: auch Review-Fälle tragen den Euro-Bankbetrag als Korrektur
    u = umsatz(betrag="-71.82", name="BITWARDEN")
    f = bewerte(usd_beleg("69.73"), [u], wissen={})
    assert not f.sicher and f.korrektur == {"auf_eur": D("71.82")}


def test_review_kategorie_vorschlag_gelernt():
    # I7
    f = bewerte(beleg(kat="1111"))
    assert not f.sicher and f.korrektur == {"kategorie_id": "2819"}


# --- Abo-Regel: mehrere Kandidaten -> genau einer innerhalb ±tage_eindeutig ---
def test_abo_naechste_zahlung_eindeutig():
    aug = umsatz(id="aug", datum=date(2026, 8, 9))
    sep = umsatz(id="sep", datum=date(2026, 9, 9))
    f = bewerte(beleg(datum=date(2026, 8, 8)), [aug, sep])
    assert f.sicher and f.umsatz.id == "aug"


def test_abo_zwei_monate_richtig_gepaart():
    b_aug, b_sep = beleg(id="ba", datum=date(2026, 8, 8)), beleg(id="bs", datum=date(2026, 9, 8))
    aug, sep = umsatz(id="aug", datum=date(2026, 8, 9)), umsatz(id="sep", datum=date(2026, 9, 9))
    faelle = rules.einstufen([b_aug, b_sep], [], [aug, sep], W, [], G, HEUTE)
    assert {(f.beleg.id, f.umsatz.id, f.sicher) for f in faelle} == {("ba", "aug", True), ("bs", "sep", True)}


def test_abo_fehlende_zahlung_beansprucht_folgemonat_nicht_sicher():
    # Aug-Zahlung fehlt: Aug-Beleg hat nur Sep-Zahlung als Kandidat -> Konflikt mit Sep-Beleg -> beide Review
    b_aug, b_sep = beleg(id="ba", datum=date(2026, 8, 8)), beleg(id="bs", datum=date(2026, 9, 8))
    sep = umsatz(id="sep", datum=date(2026, 9, 9))
    faelle = rules.einstufen([b_aug, b_sep], [], [sep], W, [], G, HEUTE)
    assert not any(f.sicher for f in faelle)


# --- Belegnummer, Aliase, echte Duplikate, Lieferanten ohne Historie ---
def nr_beleg(id="b1", nr="INV-2010207", **kw):
    b = beleg(id=id, **kw)
    return Beleg(**{**b.__dict__, "roh": {"description": nr}})


def test_duplikat_nur_bei_gleicher_belegnr():
    a, b, c = nr_beleg("1", "A-000"), nr_beleg("2", "A-001"), nr_beleg("3", "A-000")
    assert rules.duplikate([a, b, c]) == {"1", "3"}


def test_belegnr_im_zweck_ersetzt_namensabgleich():
    u = umsatz(name="PlentyONE GmbH", zweck="OID 1292970 INV-2010207 DBT 20620")
    f = bewerte(nr_beleg(lieferant="plentymarkets"), [u], wissen=rules.lerne(historie(lieferant="plentymarkets"), G))
    assert f.sicher


def test_belegnr_kein_teiltreffer():
    u = umsatz(name="PlentyONE GmbH", zweck="INV-20102079")
    assert not rules.belegnr_im_text(nr_beleg(), u)


def test_belegnr_loest_mehrere_kandidaten():
    u1 = umsatz(id="u1", zweck="INV-2010207")
    u2 = umsatz(id="u2", datum=date(2026, 9, 9), zweck="INV-9999999")
    assert [u.id for u in rules.kandidaten_beleg(nr_beleg(), [u1, u2], G)] == ["u1"]


def test_alias_name():
    g = Grenzen(aliase=(("plentymarkets", "plentyone"),))
    w = rules.lerne(historie(lieferant="plentymarkets"), G)
    f = bewerte(beleg(lieferant="plentymarkets"), [umsatz(name="PlentyONE GmbH", zweck="x")], wissen=w, g=g)
    assert f.sicher


def test_loeschkandidaten_behaelt_aeltesten():
    a = nr_beleg("100", "F38-0062")
    b = nr_beleg("200", "F38-0062")
    behalten, loeschen = rules.loeschkandidaten([b, a])
    assert behalten.id == "100" and [x.id for x in loeschen] == ["200"]


def test_loeschkandidaten_nur_entwuerfe_und_mit_nummer():
    offen = Beleg(**{**nr_beleg("200", "F38-0062").__dict__, "status": 100})
    assert rules.loeschkandidaten([nr_beleg("100", "F38-0062"), offen]) == (None, [])
    assert rules.loeschkandidaten([nr_beleg("100", ""), nr_beleg("200", "")]) == (None, [])


def test_echte_duplikat_gruppen():
    gruppen = rules.echte_duplikate([nr_beleg("1", "X-1"), nr_beleg("2", "X-1"), nr_beleg("3", "X-2")], HEUTE)
    assert [[b.id for b in g] for g in gruppen] == [["1", "2"]]


def test_lieferanten_ohne_historie():
    bs = [beleg(id="1", lieferant="REWE"), beleg(id="2", lieferant="REWE", datum=date(2026, 9, 1)),
          beleg(id="3", lieferant="Hetzner Online GmbH")]
    out = rules.lieferanten_ohne_historie(bs, W, HEUTE)
    assert [(k, n, b.id) for k, n, b in out] == [("rewe", 2, "1")]


def test_ausgeschlossener_lieferant_nie_sicher_und_beansprucht_nichts():
    g = Grenzen(ausgeschlossen=frozenset({"hetzner online"}))
    u = umsatz()
    faelle = rules.einstufen([beleg()], [], [u], W, [], g, HEUTE)
    b = [f for f in faelle if f.art == "beleg"][0]
    assert not b.sicher and b.umsatz is None and b.grund == "Lieferant ausgeschlossen"
    assert any(f.umsatz and f.umsatz.id == "u1" for f in faelle if f.art == "ohne_beleg")


def test_festgelegte_kategorie_wird_korrigiert():
    from modell import LieferantWissen
    fest = {"hetzner online": LieferantWissen("2819", "default:19", D("0"), fest=True)}
    f = bewerte(beleg(kat="2"), wissen=fest)
    assert f.sicher and f.korrektur == {"kategorie_id": "2819"}


def test_lohn_ohne_vormonatspruefung_wenn_aus():
    g = Grenzen(lohn_toleranz_prozent=None)
    assert rules.bewerte_standard(umsatz(betrag="-2900", name="Max Mustermann", zweck="Gehalt"), REGELN, W_LOHN, g).sicher
    assert rules.bewerte_standard(umsatz(betrag="-2000", name="Max Mustermann", zweck=""), REGELN, {}, g).sicher


def test_gebuehren_kartenpreis_und_waehrungsumrechnung():
    regel = Standardregel("Bankgebühren", rules.GEBUEHREN_MUSTER, "gebuehren", "70", "Bank")
    treffer = lambda zweck: bool(rules.passende_regeln(umsatz(name="", zweck=zweck), [regel]))
    assert treffer("Monatlicher Kartenpreis 09/2026")
    assert treffer("1,95 für Währungsumrechnung")


# --- Steuerart aus Verwendungszweck ---
STEUERARTEN = ((r"ums\.?\s?st|umsatzsteuer", "3"), (r"lohnst", "25230"), (r"koerpst|körperschaftst", "35738"),
               (r"gewerbesteuer", "86"), (r"kfz-steuer", "7"), (r"skapst|solskap|kistkap", "pruefen"))
G_ST = Grenzen(steuerarten=STEUERARTEN)


def test_steuerart_erkennung():
    assert rules.steuerart("STEUERNR 020 UMS.ST MRZ.26 80,00EUR", STEUERARTEN) == "3"
    assert rules.steuerart("STEUERNR LOHNST MAI 26", STEUERARTEN) == "25230"
    assert rules.steuerart("GEWERBESTEUER 2026 G EWERBESTEUER 2026", STEUERARTEN) == "86"
    assert rules.steuerart("2092961866222", STEUERARTEN) is None
    assert rules.steuerart("SKAPST 250426 SOLSKAP", STEUERARTEN) is None          # pruefen -> keine Auto-Kategorie
    assert rules.steuerart("UMS.ST MRZ LOHNST MAI", STEUERARTEN) is None          # zwei Arten -> unklar


def test_finanzamt_mit_eindeutiger_steuerart_sicher():
    u = umsatz(betrag="-80", name="Finanzamt Kiel", zweck="STEUERNR 020/296 UMS.ST MRZ.26 80,00EUR")
    f = rules.bewerte_standard(u, REGELN, {}, G_ST)
    assert f.sicher and f.korrektur == {"kategorie_id": "3"}


def test_finanzamt_ohne_steuerart_review():
    f = rules.bewerte_standard(umsatz(betrag="-266", name="Finanzamt Kiel", zweck="2092961866222"), REGELN, {}, G_ST)
    assert not f.sicher and "Steuerart" in f.grund


def test_beleg_ohne_dokument_nicht_sicher():
    f = bewerte(beleg(dok=False))
    assert not f.sicher and f.grund == "Beleg ohne Dokument (PDF fehlt)"


# --- Umbuchungen zwischen eigenen Konten ---
G_TR = Grenzen(eigene_ibans=frozenset({"DE11202208000027776310"}), transit_kategorie="40")


def test_umbuchung_eigenes_konto_ausgang_und_eingang():
    for betrag in ("-5000", "5000"):
        u = Umsatz("t1", "1", date(2026, 9, 1), D(betrag), "Web Wikinger GmbH", "Umbuchung", gegen_iban="DE11202208000027776310")
        f = rules.bewerte_standard(u, [], {}, G_TR)
        assert f.sicher and f.art == "standard" and f.regel.art == "transit" and f.regel.kategorie_id == "40"


def test_umbuchung_fremde_iban_nicht():
    u = Umsatz("t1", "1", date(2026, 9, 1), D("-5000"), "Web Wikinger GmbH", "x", gegen_iban="DE00999")
    assert rules.bewerte_standard(u, [], {}, G_TR).art == "ohne_beleg"


def test_umbuchung_commerce_nie():
    u = Umsatz("t1", "1", date(2026, 9, 1), D("-5000"), "Web Wikinger Commerce GmbH", "x", gegen_iban="DE11202208000027776310")
    assert not rules.bewerte_standard(u, [], {}, G_TR).sicher


def test_gebuehr_waehrungsumrechnung_abgekuerzt():
    regel = Standardregel("Bankgebühren", rules.GEBUEHREN_MUSTER, "gebuehren", "70", "Bank")
    assert rules.passende_regeln(umsatz(name="", zweck="1,95% für Währungsumrechn. 12,34 USD"), [regel])


# --- wechselseitig nächste Zahlung bei wiederkehrenden gleichen Beträgen ---
def test_wechselseitig_naechste_paare():
    b_aug, b_sep = beleg(id="ba", datum=date(2026, 8, 1)), beleg(id="bs", datum=date(2026, 9, 1))
    u_aug, u_sep = umsatz(id="ua", datum=date(2026, 8, 2)), umsatz(id="us", datum=date(2026, 9, 2))
    faelle = rules.einstufen([b_aug, b_sep], [], [u_aug, u_sep], W, [], G, HEUTE)
    assert {(f.beleg.id, f.umsatz.id, f.sicher) for f in faelle if f.art == "beleg"} == {("ba", "ua", True), ("bs", "us", True)}


def test_gleicher_tag_gleicher_betrag_bleibt_review():
    b1, b2 = beleg(id="b1", datum=date(2026, 9, 1)), beleg(id="b2", datum=date(2026, 9, 1))
    u1, u2 = umsatz(id="u1", datum=date(2026, 9, 2)), umsatz(id="u2", datum=date(2026, 9, 2))
    faelle = rules.einstufen([b1, b2], [], [u1, u2], W, [], G, HEUTE)
    assert not any(f.sicher for f in faelle if f.art == "beleg")
