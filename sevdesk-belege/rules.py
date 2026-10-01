"""Reine Entscheidungslogik ohne API-Zugriff: prüfen, lernen, Kandidaten, einstufen."""
import re
from collections import Counter, defaultdict
from datetime import date, timedelta
from decimal import Decimal

from modell import STICHTAG, Beleg, Fall, Grenzen, LieferantWissen, Umsatz

_RECHTSFORM = re.compile(
    r"\b(gmbh|mbh|co|kg|ag|ug|ohg|gbr|ltd|inc|llc|pte|bv|sarl|sarlau|sa|se|ek|ev|uab|oy|ab|plc)\b"
)


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


def bewerte_beleg(beleg: Beleg, kandidaten: list[Umsatz], rueck: Counter, wissen: dict,
                  dup_ids: set[str], grenzen: Grenzen, heute: date) -> Fall:
    def fall(sicher, grund, u=None, korrektur=None):
        return Fall("beleg", sicher, grund, beleg.datum or heute, umsatz=u, beleg=beleg, korrektur=korrektur or {})

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
    w = wissen.get(norm(beleg.lieferant))
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
