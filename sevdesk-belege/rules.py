"""Reine Entscheidungslogik ohne API-Zugriff: prüfen, lernen, Kandidaten, einstufen."""
import re
from collections import defaultdict
from datetime import date

from modell import STICHTAG, Beleg, Grenzen, LieferantWissen, Umsatz

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
