"""Reine Entscheidungslogik ohne API-Zugriff: prüfen, lernen, Kandidaten, einstufen."""
import re
from collections import Counter, defaultdict
from datetime import date, timedelta
from decimal import Decimal

from modell import STICHTAG, Beleg, Fall, Grenzen, LieferantWissen, Rechnung, Standardregel, Umsatz

_RECHTSFORM = re.compile(
    r"\b(gmbh|mbh|co|kg|ag|ug|ohg|gbr|ltd|inc|llc|pte|bv|sarl|sarlau|sa|se|ek|ev|uab|oy|ab|plc)\b"
)

ART_NACH_KATEGORIE = {
    "Lohn / Gehalt": "lohn",
    "Krankenkasse": "krankenkasse",
    "Miete / Pacht": "miete",
    "Kontoführung / Kartengebühren": "gebuehren",
    "bezahlte Umsatzsteuer": "finanzamt",
}
GEBUEHREN_MUSTER = r"(^|\s)(entgelt\b|kontof(ü|ue)hrung|preis für sepa|kartengeb(ü|ue)hr)"


def norm(text: str) -> str:
    t = (text or "").lower().replace(".", "")
    t = re.sub(r"[^a-z0-9äöüß]+", " ", t)
    t = _RECHTSFORM.sub(" ", t)
    return " ".join(t.split())


def name_passt(lieferant: str, umsatz: Umsatz) -> bool:
    text = norm(f"{umsatz.name} {umsatz.zweck}")
    tokens = [w for w in norm(lieferant).split() if len(w) >= 4]
    return bool(tokens) and any(w in text for w in tokens)


def ab_stichtag(objekte: list, heute: date) -> list:
    gueltig = [o for o in objekte if o.datum is not None and STICHTAG <= o.datum <= heute]
    return sorted(gueltig, key=lambda o: o.datum, reverse=True)


def duplikate(belege: list[Beleg]) -> set[str]:
    gruppen = defaultdict(list)
    for b in belege:
        gruppen[(norm(b.lieferant), b.brutto_eur, b.datum)].append(b.id)
    return {i for ids in gruppen.values() if len(ids) > 1 for i in ids}


def lerne(historie: list[Beleg], grenzen: Grenzen) -> dict[str, LieferantWissen]:
    gruppen = defaultdict(list)
    for b in historie:
        if b.kategorie_id and b.datum and b.datum >= STICHTAG and norm(b.lieferant):
            gruppen[norm(b.lieferant)].append(b)
    wissen = {}
    for key, bs in gruppen.items():
        if len(bs) < grenzen.min_historie:
            continue
        if len({b.kategorie_id for b in bs}) == 1 and len({b.steuer for b in bs}) == 1:
            letzter = max(bs, key=lambda b: b.datum)
            wissen[key] = LieferantWissen(bs[0].kategorie_id, bs[0].steuer, letzter.brutto_eur)
    return wissen


def abweichung_prozent(a: Decimal, b: Decimal) -> Decimal:
    return abs(a - b) / b * 100 if b else Decimal("Infinity")


def kandidaten_beleg(beleg: Beleg, umsaetze: list[Umsatz], grenzen: Grenzen) -> list[Umsatz]:
    if beleg.datum is None:
        return []
    von = beleg.datum - timedelta(days=grenzen.tage_vorher)
    bis = beleg.datum + timedelta(days=grenzen.tage_nachher)
    out = []
    for u in umsaetze:
        if u.betrag >= 0 or not (von <= u.datum <= bis):
            continue
        bank = -u.betrag
        if beleg.waehrung == "USD":
            if abweichung_prozent(bank, beleg.brutto_eur) <= grenzen.usd_toleranz_prozent:
                out.append(u)
        elif bank == beleg.brutto_eur:
            out.append(u)
    return out


def _vorschlag(beleg: Beleg, u: Umsatz | None, w: LieferantWissen | None) -> dict:
    """Korrekturvorschlag auch für Review-Fälle: gelernte Kategorie, USD auf Bankbetrag."""
    k = {}
    if w is not None and beleg.kategorie_id != w.kategorie_id:
        k["kategorie_id"] = w.kategorie_id
    if u is not None and beleg.waehrung == "USD" and -u.betrag != beleg.brutto_eur:
        k["brutto_eur"] = -u.betrag
    return k


def bewerte_beleg(beleg: Beleg, kandidaten: list[Umsatz], rueck: Counter, wissen: dict,
                  dup_ids: set[str], grenzen: Grenzen, heute: date) -> Fall:
    w = wissen.get(norm(beleg.lieferant))

    def fall(sicher, grund, u=None, korrektur=None):
        k = korrektur if korrektur is not None else _vorschlag(beleg, u, w)
        return Fall("beleg", sicher, grund, beleg.datum or heute, umsatz=u, beleg=beleg, korrektur=k)

    if beleg.datum is None or beleg.datum > heute:
        return fall(False, "Belegdatum fehlt oder in der Zukunft")
    if beleg.id in dup_ids:
        return fall(False, "mögliches Duplikat")
    if not kandidaten:
        return fall(False, "keine passende Zahlung")
    if len(kandidaten) > 1:
        return fall(False, f"{len(kandidaten)} mögliche Zahlungen", kandidaten[0])
    u = kandidaten[0]
    if rueck[u.id] > 1:
        return fall(False, "Zahlung passt zu mehreren Belegen", u)
    if beleg.waehrung not in ("EUR", "USD"):
        return fall(False, f"Währung {beleg.waehrung}", u)
    if not name_passt(beleg.lieferant, u):
        return fall(False, "Lieferant nicht im Zahlungstext", u)
    bank = -u.betrag
    if bank > grenzen.max_betrag:
        return fall(False, f"Betrag über {grenzen.max_betrag} €", u)
    if w is None:
        return fall(False, "Lieferant ohne eindeutige Historie", u)
    if w.steuer != beleg.steuer:
        return fall(False, f"Steuer {beleg.steuer} statt {w.steuer}", u)

    korrektur = {}
    ist = beleg.kategorie_id
    if ist != w.kategorie_id:
        if ist is not None and ist not in grenzen.standard_kategorie_ids:
            return fall(False, f"Kategorie {ist} statt gelernt {w.kategorie_id}", u)
        korrektur["kategorie_id"] = w.kategorie_id
    if beleg.waehrung == "USD" and bank != beleg.brutto_eur:
        korrektur["brutto_eur"] = bank
    if korrektur and len(beleg.positionen) != 1:
        return fall(False, "mehrere Positionen, Korrektur nicht eindeutig", u)
    return fall(True, "sicher", u, korrektur)


def kandidaten_rechnung(rechnung: Rechnung, umsaetze: list[Umsatz]) -> list[Umsatz]:
    return [u for u in umsaetze if u.betrag > 0 and u.betrag == rechnung.offen and u.datum >= rechnung.datum]


def bewerte_rechnung(rechnung: Rechnung, kandidaten: list[Umsatz], rueck: Counter) -> Fall:
    def fall(sicher, grund, u):
        return Fall("rechnung", sicher, grund, u.datum, umsatz=u, rechnung=rechnung)

    u = kandidaten[0]
    if len(kandidaten) > 1:
        return fall(False, f"{len(kandidaten)} mögliche Zahlungseingänge", u)
    if rueck[u.id] > 1:
        return fall(False, "Zahlung passt zu mehreren Rechnungen", u)
    if rechnung.typ != "RE":
        return fall(False, f"Rechnungstyp {rechnung.typ}", u)
    if rechnung.status != 200:
        return fall(False, "teilbezahlt", u)
    if not rechnung.nummer or not re.search(rf"(?<![\w-]){re.escape(rechnung.nummer)}(?![\w-])",
                                            f"{u.zweck} {u.name}", re.IGNORECASE):
        return fall(False, "Rechnungsnummer nicht im Verwendungszweck", u)
    return fall(True, "sicher", u)


def passende_regeln(umsatz: Umsatz, regeln: list[Standardregel]) -> list[Standardregel]:
    text = f"{umsatz.name} {umsatz.zweck}"
    return [r for r in regeln if re.search(r.muster, text, re.IGNORECASE)]


def bewerte_standard(umsatz: Umsatz, regeln: list[Standardregel], wissen: dict, grenzen: Grenzen) -> Fall:
    if umsatz.betrag >= 0:
        grund = "Zahlungseingang ohne passende Rechnung" if umsatz.betrag > 0 else "Betrag 0"
        return Fall("ohne_beleg", False, grund, umsatz.datum, umsatz=umsatz)
    treffer = passende_regeln(umsatz, regeln)
    if not treffer:
        return Fall("ohne_beleg", False, "kein Beleg gefunden", umsatz.datum, umsatz=umsatz)
    regel = treffer[0]

    def fall(sicher, grund):
        return Fall("standard", sicher, grund, umsatz.datum, umsatz=umsatz, regel=regel)

    if len(treffer) > 1:
        return fall(False, "mehrere Standardregeln passen")
    betrag = -umsatz.betrag
    if regel.art == "finanzamt":
        return fall(False, "Finanzamt: Steuerart bestätigen")
    if regel.art == "gebuehren":
        if betrag > grenzen.gebuehren_max:
            return fall(False, f"Gebühr über {grenzen.gebuehren_max} €")
        return fall(True, "Standardbuchung")
    if regel.art in ("lohn", "krankenkasse", "miete"):
        w = wissen.get(norm(regel.lieferant))
        if w is None:
            return fall(False, "kein Vormonatsbetrag")
        abw = abweichung_prozent(betrag, w.letzter_betrag)
        if abw > grenzen.lohn_toleranz_prozent:
            return fall(False, f"Betrag weicht {abw:.0f} % vom Vormonat ab")
        return fall(True, "Standardbuchung")
    return fall(False, f"unbekannte Regelart {regel.art}")


def einstufen(belege, rechnungen, umsaetze, wissen, regeln, grenzen, heute) -> list[Fall]:
    gueltig = ab_stichtag(belege, heute)
    vor_stichtag = [b for b in belege if b.datum is not None and b.datum < STICHTAG]
    unplausibel = [b for b in belege if b.datum is None or b.datum > heute]
    umsaetze = ab_stichtag(umsaetze, heute)
    faelle, vergeben = [], set()

    dup = duplikate(gueltig)
    # Belege vor Stichtag werden nie angefasst, beanspruchen aber ihre Zahlung (keine Doppelbuchung)
    kand = {b.id: kandidaten_beleg(b, umsaetze, grenzen) for b in gueltig + vor_stichtag}
    rueck = Counter(u.id for ks in kand.values() for u in ks)
    for b in gueltig:
        faelle.append(bewerte_beleg(b, kand[b.id], rueck, wissen, dup, grenzen, heute))
    for ks in kand.values():
        vergeben.update(u.id for u in ks)
    for b in unplausibel:
        faelle.append(bewerte_beleg(b, [], Counter(), wissen, dup, grenzen, heute))

    offen_r = [r for r in rechnungen if r.datum and r.datum >= STICHTAG]
    rest = [u for u in umsaetze if u.id not in vergeben]
    kand_r = {r.id: kandidaten_rechnung(r, rest) for r in offen_r}
    rueck_r = Counter(u.id for ks in kand_r.values() for u in ks)
    for r in offen_r:
        if kand_r[r.id]:
            faelle.append(bewerte_rechnung(r, kand_r[r.id], rueck_r))
            vergeben.update(u.id for u in kand_r[r.id])

    for u in umsaetze:
        if u.id not in vergeben:
            faelle.append(bewerte_standard(u, regeln, wissen, grenzen))

    return sorted(faelle, key=lambda f: f.datum, reverse=True)


def baue_standardregeln(historie: list[Beleg], kategorie_namen: dict[str, str], grenzen: Grenzen) -> list[Standardregel]:
    gruppen = defaultdict(list)
    for b in historie:
        if not b.hat_dokument and b.datum and b.datum >= STICHTAG and norm(b.lieferant):
            gruppen[norm(b.lieferant)].append(b)
    regeln = []
    for key, bs in gruppen.items():
        kats = {b.kategorie_id for b in bs}
        if len(bs) < grenzen.min_historie or len(kats) != 1:
            continue
        kat = kats.pop()
        art = ART_NACH_KATEGORIE.get(kategorie_namen.get(kat, ""))
        if art is None or art == "gebuehren" or (art == "finanzamt" and "finanzamt" not in key):
            continue
        lieferant = bs[0].lieferant.strip()
        regeln.append(Standardregel(f"{kategorie_namen[kat]}: {lieferant}", re.escape(lieferant), art, kat, lieferant))
    gebuehren_id = next((i for i, n in kategorie_namen.items() if n == "Kontoführung / Kartengebühren"), None)
    if gebuehren_id:
        regeln.append(Standardregel("Bankgebühren", GEBUEHREN_MUSTER, "gebuehren", gebuehren_id, "Bank"))
    return sorted(regeln, key=lambda r: r.name)


def zusammenfassung(faelle: list[Fall]) -> dict[str, tuple[int, Decimal]]:
    z = {k: [0, Decimal("0")] for k in ("sicher", "review", "ohne_beleg", "beleg_ohne_zahlung")}
    for f in faelle:
        if f.sicher:
            key = "sicher"
        elif f.art == "ohne_beleg":
            key = "ohne_beleg"
        elif f.umsatz is None:
            key = "beleg_ohne_zahlung"
        else:
            key = "review"
        betrag = abs(f.umsatz.betrag) if f.umsatz else f.beleg.brutto_eur
        z[key][0] += 1
        z[key][1] += betrag
    return {k: (n, s) for k, (n, s) in z.items()}
