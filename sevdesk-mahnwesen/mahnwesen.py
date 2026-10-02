"""Mahnwesen-Logik: Fälligkeit (Rechnungsdatum + Zahlungsziel), Tage überfällig, Mahnstufe, offen pro Kunde."""
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

STICHTAG = date(2025, 1, 1)   # alles davor wird ignoriert


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
    stufe: int = 0            # sevDesk dunningLevel der Rechnung


@dataclass(frozen=True)
class MahnInfo:
    stufe: int
    frist: date | None        # reminderDeadline der letzten Mahnung
    entwurf: bool             # letzte Mahnung noch nicht versendet


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
        typ=d.get("invoiceType") or "", status=int(d.get("status") or 0), stufe=int(d.get("dunningLevel") or 0),
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


def ab_stichtag(rechnungen: list[Rechnung]) -> list[Rechnung]:
    return [r for r in rechnungen if r.datum >= STICHTAG]


def _d(x) -> date | None:
    return date.fromisoformat(x[:10]) if x else None


def letzte_mahnungen(mahnungen: list[dict]) -> dict[str, MahnInfo]:
    """Rechnungs-ID (origin) -> letzte sevDesk-Mahnung (höchste Stufe, dann jüngstes Datum)."""
    beste = {}
    for m in mahnungen:
        origin = str((m.get("origin") or {}).get("id") or "")
        if not origin:
            continue
        key = (int(m.get("dunningLevel") or 0), m.get("invoiceDate") or "")
        if origin not in beste or key > beste[origin][0]:
            beste[origin] = (key, m)
    return {o: MahnInfo(stufe=k[0], frist=_d(m.get("reminderDeadline")),
                        entwurf=int(m.get("status") or 0) < 200 and not m.get("sendDate"))
            for o, (k, m) in beste.items()}


def aktion(r: Rechnung, info: MahnInfo | None, heute: date) -> tuple[str, int, date] | None:
    """Nächster Schritt laut sevDesk-Daten (keine festen Tagesgrenzen):
    Frist = reminderDeadline der letzten Mahnung, sonst Rechnungsdatum + Zahlungsziel.
    Entwurf vorhanden -> versenden; Frist abgelaufen -> nächste Stufe (dunningLevel + 1); sonst nichts."""
    if r.offen <= 0:
        return None
    if info is not None and info.entwurf:
        return ("entwurf versenden", info.stufe, info.frist or r.faellig)
    frist = (info.frist if info and info.frist else None) or r.faellig
    if heute <= frist:
        return None
    return ("mahnen", max(r.stufe, info.stufe if info else 0) + 1, frist)
