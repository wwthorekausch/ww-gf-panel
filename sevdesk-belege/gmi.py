"""Abgleich sevDesk-Zahlungen ohne Beleg gegen GetMyInvoices-Dokumente (nur lesend)."""
from dataclasses import dataclass
from typing import NamedTuple
from datetime import date, timedelta
from decimal import Decimal

import rules
from modell import STICHTAG, Grenzen, Umsatz

BELEG_TYPEN = ("INCOMING_INVOICE", "RECEIPT", "PAYMENT_RECEIPT", "EXPENSE_REIMBURSEMENT", "MISC")
USD_KURS = (Decimal("0.80"), Decimal("1.00"))   # plausibles EUR/USD-Verhältnis Bankbetrag / USD-Brutto


@dataclass(frozen=True)
class GmiDok:
    uid: str
    firma: str
    nr: str
    datum: date | None
    brutto: Decimal
    waehrung: str
    typ: str
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class Ergebnis:
    umsatz: Umsatz
    status: str          # in_sevdesk | nur_gmi | nicht_gefunden | mehrdeutig
    dok: GmiDok | None = None


def parse_dok(d: dict) -> GmiDok:
    return GmiDok(uid=str(d["documentUid"]), firma=d.get("companyName") or "", nr=(d.get("documentNumber") or "").strip(),
                  datum=date.fromisoformat(d["documentDate"][:10]) if d.get("documentDate") else None,
                  brutto=Decimal(str(d.get("grossAmount") or 0)), waehrung=d.get("currency") or "EUR",
                  typ=d.get("documentType") or "", tags=tuple(d.get("tags") or ()))


def _nr_im_text(nr: str, u: Umsatz) -> bool:
    import re
    return len(nr) >= 5 and bool(re.search(rf"(?<![\w-]){re.escape(nr)}(?![\w-])", f"{u.name} {u.zweck}", re.IGNORECASE))


def kandidaten(u: Umsatz, docs: list[GmiDok], grenzen: Grenzen) -> list[GmiDok]:
    if u.betrag >= 0:
        return []
    bank = -u.betrag
    out = []
    for d in docs:
        if d.datum is None or not (d.datum - timedelta(days=grenzen.tage_vorher) <= u.datum
                                   <= d.datum + timedelta(days=grenzen.tage_nachher)):
            continue
        if d.waehrung == "EUR":
            betrag_ok = d.brutto == bank
        elif d.waehrung == "USD" and d.brutto:
            betrag_ok = USD_KURS[0] <= bank / d.brutto <= USD_KURS[1]
        else:
            betrag_ok = False
        if betrag_ok and (_nr_im_text(d.nr, u) or rules.name_passt(d.firma, u, grenzen.aliase)):
            out.append(d)
    if len(out) > 1:
        mit_nr = [d for d in out if _nr_im_text(d.nr, u)]
        if len(mit_nr) == 1:
            return mit_nr
        nah = [d for d in out if abs((u.datum - d.datum).days) <= grenzen.tage_eindeutig]
        if len(nah) == 1:
            return nah
    return out


def einstufen(umsaetze: list[Umsatz], docs: list[GmiDok], sevdesk_nummern: set[str], grenzen: Grenzen) -> list[Ergebnis]:
    erg = []
    for u in umsaetze:
        k = kandidaten(u, docs, grenzen)
        if not k:
            erg.append(Ergebnis(u, "nicht_gefunden"))
        elif len(k) > 1:
            erg.append(Ergebnis(u, "mehrdeutig", k[0]))
        else:
            schluessel = k[0].nr or f"GMI-{k[0].uid}"     # so steht es nach dem Upload in der sevDesk-Beschreibung
            erg.append(Ergebnis(u, "in_sevdesk" if schluessel in sevdesk_nummern else "nur_gmi", k[0]))
    return erg


class UploadPlan(NamedTuple):
    sicher: bool
    grund: str
    kategorie_id: str | None
    steuerart: str | None
    satz: Decimal | None
    betrag: Decimal | None


def upload_plan(e: Ergebnis, wissen: dict, grenzen: Grenzen) -> UploadPlan:
    """Darf das GMI-Dokument als Beleg nach sevDesk hochgeladen und der Zahlung zugeordnet werden?"""
    nein = lambda grund: UploadPlan(False, grund, None, None, None, None)
    if e.status != "nur_gmi" or e.dok is None:
        return nein(f"Status {e.status}")
    if e.dok.datum is None or e.dok.datum < STICHTAG or e.umsatz.datum < STICHTAG:
        return nein("Belegdatum vor 2025 oder fehlt")
    if any(t.lower() == "sevdesk" for t in e.dok.tags):
        return nein("in GetMyInvoices schon als Sevdesk getaggt")
    w = wissen.get(rules.norm(e.dok.firma)) or wissen.get(rules.norm(e.umsatz.name))
    if w is None:
        return nein("Lieferant ohne Kategorie")
    steuerart, _, saetze = w.steuer.partition(":")
    if not saetze or "," in saetze:
        return nein(f"Steuer nicht eindeutig ({w.steuer})")
    betrag = -e.umsatz.betrag
    if betrag > grenzen.max_betrag:
        return nein(f"Betrag über {grenzen.max_betrag} €")
    return UploadPlan(True, "sicher", w.kategorie_id, steuerart, Decimal(saetze), betrag)
