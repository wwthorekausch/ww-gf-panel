"""Mahnwesen-Logik: Fälligkeit (Rechnungsdatum + Zahlungsziel), Tage überfällig, Mahnstufe, offen pro Kunde."""
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal


@dataclass(frozen=True)
class Rechnung:
    id: str
    nummer: str
    kunde: str
    kundennummer: str
    datum: date
    faellig: date
    brutto: Decimal
    offen: Decimal
    typ: str
    status: int


def _dec(x) -> Decimal:
    return Decimal(str(x)) if x not in (None, "") else Decimal("0")


def parse(d: dict) -> Rechnung:
    datum = date.fromisoformat(d["invoiceDate"][:10])
    ziel = int(d.get("timeToPay") or 0)
    kontakt = d.get("contact") or {}
    return Rechnung(
        id=str(d["id"]), nummer=d.get("invoiceNumber") or "",
        kunde=kontakt.get("name") or d.get("addressName") or "?", kundennummer=str(kontakt.get("customerNumber") or ""),
        datum=datum, faellig=datum + timedelta(days=ziel),
        brutto=_dec(d.get("sumGross")), offen=_dec(d.get("sumGross")) - _dec(d.get("paidAmount")),
        typ=d.get("invoiceType") or "", status=int(d.get("status") or 0),
    )


def tage_ueberfaellig(r: Rechnung, heute: date) -> int:
    return (heute - r.faellig).days


def mahnstufe(tage: int, schwellen: tuple[int, int, int]) -> int:
    return sum(1 for s in schwellen if tage >= s)


def ueberfaellig(rechnungen: list[Rechnung], heute: date) -> list[Rechnung]:
    """Offene Forderungen (Betrag > 0) mit überschrittenem Zahlungsziel, älteste zuerst."""
    xs = [r for r in rechnungen if r.offen > 0 and tage_ueberfaellig(r, heute) > 0]
    return sorted(xs, key=lambda r: r.faellig)


def gemahnt(mahnungen: list[dict]) -> dict[str, int]:
    """Original-Rechnungs-ID -> Anzahl sevDesk-Mahnungen (Typ MA, verknüpft über origin)."""
    zaehler = defaultdict(int)
    for m in mahnungen:
        origin = (m.get("origin") or {}).get("id")
        if origin:
            zaehler[str(origin)] += 1
    return dict(zaehler)


def offen_pro_kunde(rechnungen: list[Rechnung], heute: date) -> list[tuple[str, Decimal, Decimal, int]]:
    """(Kunde, offen gesamt, davon überfällig, Anzahl Belege) — Gutschriften mindern, größter Betrag zuerst."""
    summe, faellig, anzahl = defaultdict(Decimal), defaultdict(Decimal), defaultdict(int)
    for r in rechnungen:
        summe[r.kunde] += r.offen
        anzahl[r.kunde] += 1
        if r.offen > 0 and tage_ueberfaellig(r, heute) > 0:
            faellig[r.kunde] += r.offen
    out = [(k, summe[k], faellig[k], anzahl[k]) for k in summe]
    return sorted(out, key=lambda t: t[1], reverse=True)
