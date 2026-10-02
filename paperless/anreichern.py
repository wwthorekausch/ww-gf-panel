"""Paperless-Felder aus sevDesk/GetMyInvoices ergänzen. Reine Logik: vorhandene Werte werden nie überschrieben."""
import re
from dataclasses import dataclass
from datetime import date
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
    waehrung: str = "EUR"


def _norm(t: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9äöüß]+", " ", (t or "").lower()).split())


def _text(doc: dict) -> str:
    return f"{doc.get('title') or ''} {doc.get('original_file_name') or ''} {doc.get('content') or ''}"


def re_nummer(doc: dict) -> str | None:
    """Rechnungsnummer RE-xxxx: Treffer in Titel/Dateiname gewinnt, sonst genau eine im Text."""
    muster = r"(?<![A-Za-z0-9])RE-\d{4,6}(?![0-9])"   # _ trennt (Dateinamen)
    kopf = set(re.findall(muster, f"{doc.get('title') or ''} {doc.get('original_file_name') or ''}"))
    if len(kopf) == 1:
        return kopf.pop()
    alle = set(re.findall(muster, doc.get("content") or ""))
    return alle.pop() if len(alle) == 1 else None


def _treffer(text: str, belege: list[dict]) -> list[dict]:
    return [b for b in belege if len(b.get("nr") or "") >= 5 and re.search(r"\d", b["nr"])
            and re.search(rf"(?<![A-Za-z0-9-]){re.escape(b['nr'])}(?![A-Za-z0-9-])", text, re.IGNORECASE)]  # _ trennt


def _eindeutig(treffer: list[dict]) -> dict | None:
    if not treffer or len({b["nr"].lower() for b in treffer}) != 1:
        return None
    # dieselbe Nummer mehrfach (gebuchter Beleg + Entwurfskopie): gebuchten bzw. ältesten nehmen
    return sorted(treffer, key=lambda b: (-int(b.get("status") or 0), int(b["id"]) if str(b["id"]).isdigit() else 0))[0]


def betrag_im_text(betrag: Decimal | None, text: str) -> bool:
    if betrag is None:
        return False
    b = abs(betrag).quantize(Decimal("0.01"))
    ganz, cent = f"{b:.2f}".split(".")
    tausend_de = f"{int(ganz):,}".replace(",", ".")
    tausend_en = f"{int(ganz):,}"
    formen = {f"{ganz},{cent}", f"{ganz}.{cent}", f"{tausend_de},{cent}", f"{tausend_en}.{cent}"}
    return any(re.search(rf"(?<![\d.,]){re.escape(f)}(?!\d)", text) for f in formen)


def finde_beleg(doc: dict, belege: list[dict]) -> dict | None:
    """Beleg, dessen Nummer im Dokument steht. Titel/Dateiname geht vor Text; Nummer muss eindeutig sein.
    Treffer nur im Text zählen nur, wenn auch der Bruttobetrag im Text steht (sonst z. B. Postleitzahl 24114)."""
    kopf = _eindeutig(_treffer(f"{doc.get('title') or ''} {doc.get('original_file_name') or ''}", belege))
    if kopf:
        return kopf
    text = _text(doc)
    return _eindeutig([b for b in _treffer(text, belege) if betrag_im_text(b.get("brutto"), text)])


def netto_pruefen(brutto: Decimal | None, netto: Decimal | None, text: str) -> Decimal | None:
    """Netto == Brutto ist verdächtig (Quelle ohne USt gebucht): nur übernehmen, was der Text belegt."""
    if netto is None or brutto is None or netto != brutto:
        return netto
    for satz in (Decimal("1.19"), Decimal("1.07")):
        n = (brutto / satz).quantize(Decimal("0.01"))
        if betrag_im_text(n, text):
            return n
    return None


def geld(betrag: Decimal, waehrung: str = "EUR") -> str:
    return f"{(waehrung or 'EUR').upper()}{betrag.quantize(Decimal('0.01'))}"


def zahlart(gmi_methode: str | None) -> str | None:
    return ZAHLART.get(gmi_methode or "")


PLATZHALTER = {"keine angabe", "sonstiges", "unbekannt", "diverse"}


def korrespondent_tauglich(name: str | None) -> bool:
    key = _norm(name or "")
    return bool(key) and key not in PLATZHALTER


def aehnlich(a_: str, b_: str) -> bool:
    """Gleiche Firma unter anderem Namen: ein Name im anderen enthalten oder erstes Wort teilt 6 Zeichen."""
    x, y = _norm(a_), _norm(b_)
    if not x or not y:
        return False
    if x in y or y in x:
        return True
    w1, w2 = x.split()[0], y.split()[0]
    return len(w1) >= 6 and len(w2) >= 6 and w1[:6] == w2[:6]


def korrespondent_id(name: str, korrespondenten: list[dict]) -> int | None:
    key = _norm(name).replace(" ", "")
    for k in korrespondenten:
        if _norm(k["name"]).replace(" ", "") == key:
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
            "Brutto": geld(quelle.brutto, quelle.waehrung) if quelle.brutto is not None else None,
            "Netto": geld(quelle.netto, quelle.waehrung) if quelle.netto is not None else None,
            "Firma": quelle.firma if korrespondent_tauglich(quelle.firma) else None,
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


def firma_fuer_sevdesk(doc: dict, quelle: Quelle | None, cf: dict[str, int]) -> str | None:
    """Firma aus Paperless (OCR-geprüft, hat Vorrang), wenn sie vom sevDesk-Beleg abweicht — sonst None."""
    firma = {f["field"]: f.get("value") for f in doc.get("custom_fields") or []}.get(cf.get("Firma"))
    if not quelle or not quelle.sevdesk_id or not korrespondent_tauglich(firma):
        return None
    return None if quelle.firma and aehnlich(firma, quelle.firma) else firma


KLAERBAR = ("Rechnungsnummer", "Brutto", "Netto", "Firma", "SevdeskID", "Rechnungstyp", "Zahlart")


def _sollwerte(quelle: Quelle, optionen: dict) -> dict:
    return {
        "Rechnungsnummer": quelle.nummer,
        "Brutto": geld(quelle.brutto, quelle.waehrung) if quelle.brutto is not None else None,
        "Netto": geld(quelle.netto, quelle.waehrung) if quelle.netto is not None else None,
        "Firma": quelle.firma if korrespondent_tauglich(quelle.firma) else None,
        "Kundenummer": quelle.kundennummer,
        "SevdeskID": quelle.sevdesk_id,
        "Rechnungstyp": optionen.get("Rechnungstyp", {}).get(quelle.rechnungstyp or ""),
        "Zahlart": optionen.get("Zahlart", {}).get(quelle.zahlart or ""),
    }


def korrektur(doc: dict, quelle: Quelle | None, cf: dict[str, int], optionen: dict, korrespondent_id,
              korrespondent_namen: dict | None = None) -> dict | None:
    """Abweichungen zur Quelle (überschreibt!). Ohne Quelle nur leeren, wenn eine SevdeskID gesetzt ist
    (= früherer Tool-Treffer, der nicht mehr passt). Ähnlicher vorhandener Korrespondent bleibt. Nur nach Rückfrage."""
    vorhanden = {f["field"]: f.get("value") for f in doc.get("custom_fields") or []}
    if quelle is None and vorhanden.get(cf.get("SevdeskID")) in (None, ""):
        return None
    soll = dict(vorhanden)
    if quelle is not None:
        sid = cf.get("SevdeskID")
        quellwechsel = vorhanden.get(sid) not in (None, "") and vorhanden.get(sid) != quelle.sevdesk_id
        for name, wert in _sollwerte(quelle, optionen).items():
            fid = cf.get(name)
            if fid is None:
                continue
            if wert not in (None, ""):
                soll[fid] = wert
            elif quellwechsel and name in KLAERBAR and fid in soll:
                soll[fid] = None          # Wert stammte vom alten (falschen) Treffer
    else:
        for name in KLAERBAR:
            fid = cf.get(name)
            if fid in soll:
                soll[fid] = None
    body = {}
    if soll != vorhanden:
        body["custom_fields"] = [{"field": f, "value": v} for f, v in soll.items()]
    ziel_korr = korrespondent_id if quelle is not None else None
    aktuell = (korrespondent_namen or {}).get(doc.get("correspondent"), "")
    behalten = quelle is not None and quelle.firma and aktuell and aehnlich(aktuell, quelle.firma)
    if not behalten and (quelle is None or korrespondent_id) and doc.get("correspondent") != ziel_korr:
        body["correspondent"] = ziel_korr
    return body or None


ZAHLUNGSBELEG = re.compile(r"payment receipt|zahlungsbest(ä|ae)tigung|zahlungsbeleg|receipt for your payment", re.IGNORECASE)


def ist_zahlungsbeleg(doc: dict) -> bool:
    return bool(ZAHLUNGSBELEG.search(_text(doc)))


def finde_ueber_firma_betrag(doc: dict, belege: list[dict], tage: int = 10) -> dict | None:
    """Stufe 2 ohne Nummer: Firma (erstes Wort >= 5 Zeichen) und Bruttobetrag stehen im OCR-Text,
    Belegdatum höchstens `tage` vom Dokumentdatum entfernt, genau ein Beleg (gleiche Nr. mehrfach erlaubt)."""
    text = _text(doc)
    ntext = _norm(text)
    try:
        doc_datum = date.fromisoformat(str(doc.get("created") or "")[:10])
    except ValueError:
        return None
    treffer = []
    for b in belege:
        wort = (_norm(b.get("firma") or "").split() or [""])[0]
        if len(wort) < 5 or not korrespondent_tauglich(b.get("firma")) or wort not in ntext:
            continue
        if b.get("datum") is None or abs((b["datum"] - doc_datum).days) > tage:
            continue
        if betrag_im_text(b.get("brutto"), text):
            treffer.append(b)
    if not treffer or len({(b.get("nr") or b["id"]).lower() for b in treffer}) != 1:
        return None
    return sorted(treffer, key=lambda b: -int(b.get("status") or 0))[0]
