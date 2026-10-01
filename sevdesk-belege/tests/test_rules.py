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
    assert f.sicher and f.korrektur == {"brutto_eur": D("71.82")}


def test_usd_ausserhalb_toleranz_kein_kandidat():
    u = umsatz(betrag="-71.83", name="BITWARDEN")        # +3.011 %
    f = bewerte(usd_beleg("69.73"), [u], wissen=W_USD)
    assert not f.sicher and f.grund == "keine passende Zahlung"


def test_usd_exakt_keine_korrektur():
    u = umsatz(betrag="-69.73", name="BITWARDEN")
    f = bewerte(usd_beleg("69.73"), [u], wissen=W_USD)
    assert f.sicher and f.korrektur == {}


def test_eingang_ist_kein_kandidat_fuer_beleg():
    f = bewerte(beleg(), [umsatz(betrag="49.99")])
    assert f.grund == "keine passende Zahlung"
