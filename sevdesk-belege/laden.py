"""Liest sevDesk-Daten (nur GET) und wandelt sie in Datenklassen."""
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from modell import STICHTAG, Beleg, Position, Rechnung, Umsatz

SEITE = 1000


def _datum(s) -> date | None:
    return date.fromisoformat(s[:10]) if s else None


def _dec(s) -> Decimal:
    return Decimal(str(s)) if s not in (None, "") else Decimal("0")


def alle(client, path: str, params: dict) -> list[dict]:
    out, offset = [], 0
    while True:
        batch = client.get(path, params={**params, "limit": SEITE, "offset": offset})["objects"]
        out += batch
        if len(batch) < SEITE:
            return out
        offset += SEITE


def parse_umsatz(d: dict) -> Umsatz:
    return Umsatz(id=str(d["id"]), konto_id=str(d["checkAccount"]["id"]), datum=_datum(d["valueDate"]),
                  betrag=_dec(d["amount"]), name=d.get("payeePayerName") or "", zweck=d.get("paymtPurpose") or "",
                  gegen_iban=(d.get("payeePayerAcctNo") or "").replace(" ", "").upper())


def parse_position(d: dict) -> Position:
    return Position(id=str(d["id"]), kategorie_id=str(d["accountingType"]["id"]),
                    steuersatz=_dec(d.get("taxRate")), brutto=_dec(d.get("sumGross")))


def parse_beleg(d: dict, positionen: list[Position]) -> Beleg:
    fremd = d.get("sumGrossForeignCurrency")
    return Beleg(
        id=str(d["id"]),
        datum=_datum(d.get("voucherDate")),
        lieferant=d.get("supplierName") or (d.get("supplier") or {}).get("name") or "",
        brutto_eur=_dec(d.get("sumGross")),
        brutto_fremd=_dec(fremd) if fremd not in (None, "", "0") else None,
        waehrung=d.get("currency") or "EUR",
        status=int(d["status"]),
        steuerart=d.get("taxType") or "",
        positionen=tuple(positionen),
        hat_dokument=bool(d.get("document")),
        roh=d,
    )


def parse_rechnung(d: dict) -> Rechnung:
    return Rechnung(id=str(d["id"]), nummer=d.get("invoiceNumber") or "", datum=_datum(d.get("invoiceDate")),
                    typ=d.get("invoiceType") or "", status=int(d["status"]),
                    offen=_dec(d.get("sumGross")) - _dec(d.get("paidAmount")),
                    kunde=(d.get("contact") or {}).get("name") or d.get("addressName") or "")


def kategorien(client) -> dict[str, str]:
    return {str(a["id"]): a["name"] for a in alle(client, "AccountingType", {})}


@dataclass
class Daten:
    belege: list[Beleg]          # Status 50 + 100 (Eingangsbelege, creditDebit C)
    historie: list[Beleg]        # Status 1000 ab STICHTAG
    rechnungen: list[Rechnung]   # Status 200 + 750
    umsaetze: list[Umsatz]       # Status 100 ab STICHTAG


def lade(client) -> Daten:
    start = STICHTAG.isoformat()
    roh_offen = [v for st in (50, 100) for v in alle(client, "Voucher", {"status": st, "embed": "supplier"})
                 if v.get("creditDebit") == "C"]
    roh_hist = [v for v in alle(client, "Voucher", {"status": 1000, "startDate": start, "embed": "supplier"})
                if (v.get("voucherDate") or "") >= start]
    ids = {str(v["id"]) for v in roh_offen + roh_hist}
    pos = defaultdict(list)
    for p in alle(client, "VoucherPos", {}):
        vid = str(p["voucher"]["id"])
        if vid in ids:
            pos[vid].append(parse_position(p))
    rechnungen = [parse_rechnung(r) for st in (200, 750)
                  for r in alle(client, "Invoice", {"status": st, "embed": "contact"})]
    umsaetze = [parse_umsatz(t) for t in alle(client, "CheckAccountTransaction", {"status": 100, "startDate": start})]
    return Daten(
        belege=[parse_beleg(v, pos[str(v["id"])]) for v in roh_offen],
        historie=[parse_beleg(v, pos[str(v["id"])]) for v in roh_hist],
        rechnungen=rechnungen,
        umsaetze=umsaetze,
    )
