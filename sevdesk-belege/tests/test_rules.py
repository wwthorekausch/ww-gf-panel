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
