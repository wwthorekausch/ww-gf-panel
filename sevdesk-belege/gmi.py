"""Abgleich sevDesk-Zahlungen ohne Beleg gegen GetMyInvoices-Dokumente (nur lesend)."""
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

import rules
from modell import Grenzen, Umsatz

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


@dataclass(frozen=True)
class Ergebnis:
    umsatz: Umsatz
    status: str          # in_sevdesk | nur_gmi | nicht_gefunden | mehrdeutig
    dok: GmiDok | None = None


def parse_dok(d: dict) -> GmiDok:
    return GmiDok(uid=str(d["documentUid"]), firma=d.get("companyName") or "", nr=(d.get("documentNumber") or "").strip(),
                  datum=date.fromisoformat(d["documentDate"][:10]) if d.get("documentDate") else None,
                  brutto=Decimal(str(d.get("grossAmount") or 0)), waehrung=d.get("currency") or "EUR",
                  typ=d.get("documentType") or "")


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
            erg.append(Ergebnis(u, "in_sevdesk" if k[0].nr and k[0].nr in sevdesk_nummern else "nur_gmi", k[0]))
    return erg
