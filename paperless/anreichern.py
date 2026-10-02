"""Paperless-Felder aus sevDesk/GetMyInvoices ergänzen. Reine Logik: vorhandene Werte werden nie überschrieben."""
import re
from dataclasses import dataclass
from decimal import Decimal

ZAHLART = {"cc": "Kreditkarte", "direct_debit": "Lastschrift", "paypal": "Paypal", "bank_transfer": "Rechnung"}
RECHNUNGSTYP = {"RE": "Rechnung", "ER": "Rechnung", "TR": "Rechnung", "AR": "Rechnung", "GU": "Gutschrift", "SR": "Stornorechnung"}


@dataclass(frozen=True)
class Quelle:
    nummer: str | None = None
    brutto: Decimal | None = None
    netto: Decimal | None = None
    firma: str | None = None
    kundennummer: str | None = None
    sevdesk_id: str | None = None
    rechnungstyp: str | None = None
    zahlart: str | None = None


def _norm(t: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9äöüß]+", " ", (t or "").lower()).split())


def _text(doc: dict) -> str:
    return f"{doc.get('title') or ''} {doc.get('original_file_name') or ''} {doc.get('content') or ''}"


def re_nummer(doc: dict) -> str | None:
    """Rechnungsnummer RE-xxxx: Treffer in Titel/Dateiname gewinnt, sonst genau eine im Text."""
    muster = r"\bRE-\d{4,6}\b"
    kopf = set(re.findall(muster, f"{doc.get('title') or ''} {doc.get('original_file_name') or ''}"))
    if len(kopf) == 1:
        return kopf.pop()
    alle = set(re.findall(muster, doc.get("content") or ""))
    return alle.pop() if len(alle) == 1 else None


def finde_beleg(doc: dict, belege: list[dict]) -> dict | None:
    """Eingangsbeleg, dessen Belegnummer (>= 5 Zeichen) im Dokument steht — nur bei genau einem Treffer."""
    text = _text(doc)
    treffer = [b for b in belege if len(b.get("nr") or "") >= 5
               and re.search(rf"(?<![\w-]){re.escape(b['nr'])}(?![\w-])", text, re.IGNORECASE)]
    return treffer[0] if len(treffer) == 1 else None


def geld(betrag: Decimal) -> str:
    return f"EUR{betrag.quantize(Decimal('0.01'))}"


def zahlart(gmi_methode: str | None) -> str | None:
    return ZAHLART.get(gmi_methode or "")


PLATZHALTER = {"keine angabe", "sonstiges", "unbekannt", "diverse"}


def korrespondent_tauglich(name: str | None) -> bool:
    key = _norm(name or "")
    return bool(key) and key not in PLATZHALTER


def korrespondent_id(name: str, korrespondenten: list[dict]) -> int | None:
    key = _norm(name)
    for k in korrespondenten:
        if _norm(k["name"]) == key:
            return k["id"]
    return None


def plan(doc: dict, quelle: Quelle | None, cf: dict[str, int], optionen: dict, korrespondent_id: int | None,
         speicherpfad_id: int | None) -> dict | None:
    """PATCH-Body nur mit fehlenden Werten; vorhandene Custom-Field-Werte werden unverändert mitgeschickt."""
    body = {}
    vorhanden = {f["field"]: f.get("value") for f in doc.get("custom_fields") or []}
    if quelle is not None:
        neu = {
            "Rechnungsnummer": quelle.nummer,
            "Brutto": geld(quelle.brutto) if quelle.brutto is not None else None,
            "Netto": geld(quelle.netto) if quelle.netto is not None else None,
            "Firma": quelle.firma,
            "Kundenummer": quelle.kundennummer,
            "SevdeskID": quelle.sevdesk_id,
            "Rechnungstyp": optionen.get("Rechnungstyp", {}).get(quelle.rechnungstyp or ""),
            "Zahlart": optionen.get("Zahlart", {}).get(quelle.zahlart or ""),
        }
        ergaenzt = dict(vorhanden)
        for name, wert in neu.items():
            fid = cf.get(name)
            if fid is not None and wert not in (None, "") and vorhanden.get(fid) in (None, ""):
                ergaenzt[fid] = wert
        if ergaenzt != vorhanden:
            body["custom_fields"] = [{"field": f, "value": v} for f, v in ergaenzt.items()]
        if korrespondent_id and not doc.get("correspondent"):
            body["correspondent"] = korrespondent_id
    if speicherpfad_id and not doc.get("storage_path"):
        body["storage_path"] = speicherpfad_id
    return body or None
