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


def _kompakt(t: str) -> str:
    import re
    return re.sub(r"[^a-z0-9äöüß]", "", (t or "").lower())


def absprache(kunde: str, absprachen: list[dict], rechnung: str | None = None) -> dict | None:
    """Absprache für Kunde (Name-Teilstring ohne Sonderzeichen), optional nur für eine Rechnungsnummer."""
    k = _kompakt(kunde)
    for a in absprachen:
        if _kompakt(a.get("kunde", "")) and _kompakt(a["kunde"]) in k:
            if a.get("rechnung") and a["rechnung"] != rechnung:
                continue
            return a
    return None


def mahnbar(r: Rechnung, info: MahnInfo | None, absprachen: list[dict], heute: date) -> tuple[bool, str, int | None]:
    """Darf für diese Rechnung jetzt ein Mahnungs-Entwurf angelegt werden?"""
    if r.datum < STICHTAG:
        return False, "Rechnung vor 2025", None
    ab = absprache(r.kunde, absprachen, r.nummer)
    if ab:
        return False, f"Absprache: {ab['aktion']} ({ab.get('notiz', '')})", None
    a = aktion(r, info, heute)
    if a is None:
        return False, "Frist noch nicht abgelaufen oder nichts offen", None
    if a[0] != "mahnen":
        return False, "Mahnungs-Entwurf existiert schon — erst versenden", None
    return True, f"{a[1]}. Mahnung", a[1]


def sendbar(entwurf: dict, original: Rechnung, absprachen: list[dict]) -> tuple[bool, str]:
    if entwurf.get("invoiceType") != "MA":
        return False, "keine Mahnung"
    if int(entwurf.get("status") or 0) >= 200 or entwurf.get("sendDate"):
        return False, "Mahnung schon versendet"
    if original.datum < STICHTAG:
        return False, "Rechnung vor 2025"
    if original.offen <= 0:
        return False, "Rechnung nicht mehr offen"
    ab = absprache(original.kunde, absprachen, original.nummer)
    if ab:
        return False, f"Absprache: {ab['aktion']}"
    return True, "ok"


def _eur_de(b: Decimal) -> str:
    return f"{b:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def mahn_mail(nummer: str, datum: date, betrag: Decimal, frist: date, stufe: int) -> dict:
    titel = "Zahlungserinnerung" if stufe <= 1 else f"{stufe}. Mahnung"
    text = (
        "Sehr geehrte Damen und Herren,<br><br>"
        + ("sicher ist es Ihrer Aufmerksamkeit entgangen: " if stufe <= 1 else "trotz unserer Erinnerung ist ")
        + ("Für" if stufe <= 1 else "für") + f" unsere Rechnung <b>{nummer} vom {datum:%d.%m.%Y}</b> über <b>{_eur_de(betrag)}</b> "
        + ("konnten wir bisher keinen Zahlungseingang feststellen." if stufe <= 1 else "bisher keine Zahlung eingegangen.")
        + f"<br><br>Wir bitten Sie, den offenen Betrag bis zum <b>{frist:%d.%m.%Y}</b> auf das in der Rechnung genannte "
          "Konto zu überweisen. Sollte sich Ihre Zahlung mit diesem Schreiben überschnitten haben, betrachten Sie diese "
          "Erinnerung bitte als gegenstandslos.<br><br>"
        + f"Die {titel} finden Sie im Anhang.<br><br>Mit freundlichen Grüßen<br>Web Wikinger GmbH"
    )
    return {"subject": f"{titel} zur Rechnung {nummer}", "text": text}


RECHNUNGSADRESSE_KEY = "8"   # sevDesk CommunicationWayKey "Rechnungsadresse"


def waehle_mail(wege: list[dict]) -> str | None:
    """Empfänger: Rechnungsadresse > Hauptadresse > einzige Adresse; sonst None (nicht raten)."""
    mails = [w for w in wege if w.get("type") == "EMAIL" and w.get("value")]
    for auswahl in ([w for w in mails if str((w.get("key") or {}).get("id")) == RECHNUNGSADRESSE_KEY],
                    [w for w in mails if str(w.get("main")) in ("1", "True", "true")], mails):
        if len(auswahl) == 1:
            return auswahl[0]["value"]
        if len(auswahl) > 1:
            return None
    return None


def neue_frist_ok(alt: date | None, neu: date, heute: date) -> tuple[bool, str]:
    if alt is not None and alt >= heute:
        return False, f"alte Frist {alt:%d.%m.%Y} läuft noch"
    if neu <= heute:
        return False, "neue Frist muss in der Zukunft liegen"
    return True, "ok"


def gebuehr_erlassbar(ma: dict, original: dict, auch_vor_2025: bool = False) -> tuple[bool, str]:
    """Offene Mahngebühr einer sonst bezahlten Rechnung per Minderung (bookAmount 0 €, Typ O) abschließen?"""
    if ma.get("invoiceType") != "MA":
        return False, "keine Mahnung"
    if str(ma.get("status")) != "750":
        return False, f"Mahnung Status {ma.get('status')} (nicht teilbezahlt)"
    if not auch_vor_2025 and (ma.get("invoiceDate") or "")[:10] < STICHTAG.isoformat():
        return False, "vor 2025"
    if str(original.get("status")) != "1000":
        return False, "Rechnung nicht bezahlt"
    if _dec(ma.get("sumGross")) != 0 or _dec(ma.get("paidAmount")) != 0:
        return False, "Betrag/Zahlung auf der Mahnung ≠ 0 (prüfen)"
    return True, "ok"
