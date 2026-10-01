"""Alle Schreibzugriffe auf sevDesk. Guards erzwingen die harten Regeln (siehe CLAUDE.md im Root)."""
import re
from decimal import Decimal

import db
from rules import norm
from modell import STICHTAG, Beleg, Fall, Standardregel, Umsatz

ERLAUBT = [(m, re.compile(p)) for m, p in (
    ("post", r"^Voucher/Factory/saveVoucher$"),
    ("put", r"^Voucher/\d+/bookAmount$"),
    ("put", r"^Invoice/\d+/bookAmount$"),
    ("delete", r"^Voucher/\d+$"),          # nur über loesche_duplikat (Entwurf-Duplikate)
)]
ROH_FELDER = ("id", "objectName", "voucherDate", "supplier", "supplierName", "description", "document",
              "creditDebit", "taxType", "voucherType", "currency", "deliveryDate", "paymentDeadline")


class RegelVerletzung(Exception):
    """Harte Regel verletzt — Lauf muss komplett stoppen."""


class Abbruch(Exception):
    """Dieser Fall wird abgebrochen und kommt zur Prüfung; Lauf geht weiter."""


class AbbruchNachSchreiben(Abbruch):
    """Abbruch, nachdem in diesem Fall schon geschrieben wurde — Lauf muss stoppen (Zustand prüfen)."""


class LimitErreicht(Exception):
    """Maximale Anzahl Buchungen pro Lauf erreicht."""


def zuordnen_body(umsatz: Umsatz, betrag: Decimal) -> dict:
    return {
        "amount": float(abs(betrag)) * (-1 if umsatz.betrag < 0 else 1),   # Vorzeichen wie Umsatz (Ausgabe negativ)
        "date": umsatz.datum.isoformat(),
        "type": "N",
        "checkAccount": {"id": int(umsatz.konto_id), "objectName": "CheckAccount"},
        "checkAccountTransaction": {"id": int(umsatz.id), "objectName": "CheckAccountTransaction"},
        "createFeed": True,
    }


def beleg_speichern_body(beleg: Beleg, kategorie_id: str, brutto: Decimal) -> dict:
    voucher = {k: beleg.roh[k] for k in ROH_FELDER if beleg.roh.get(k) not in (None, "")}
    voucher.update({"id": int(beleg.id), "objectName": "Voucher", "mapAll": True, "status": 100})
    if beleg.waehrung == "USD" and beleg.brutto_fremd and brutto != beleg.brutto_eur:
        kurs = (brutto / beleg.brutto_fremd).quantize(Decimal("0.000001"))
        voucher["propertyExchangeRate"] = f"{kurs.normalize():f}"
    einzel = len(beleg.positionen) == 1
    positionen = [{
        "id": int(p.id), "objectName": "VoucherPos", "mapAll": True,
        "accountingType": {"id": int(kategorie_id if einzel else p.kategorie_id), "objectName": "AccountingType"},
        "taxRate": float(p.steuersatz),
        "sumGross": float(brutto if einzel else p.brutto),
        "net": False,
    } for p in beleg.positionen]
    return {"voucher": voucher, "voucherPosSave": positionen, "voucherPosDelete": None}


def usd_auf_eur_body(beleg: Beleg, bank: Decimal, kategorie_id: str | None = None) -> dict:
    """Fremdwährungsbeleg auf EUR mit tatsächlich abgebuchtem Betrag umstellen (PDF bleibt Originalrechnung)."""
    voucher = {k: beleg.roh[k] for k in ROH_FELDER if beleg.roh.get(k) not in (None, "")}
    voucher.update({"id": int(beleg.id), "objectName": "Voucher", "mapAll": True, "status": 100, "currency": "EUR"})
    p = beleg.positionen[0]
    return {"voucher": voucher, "voucherPosSave": [{
        "id": int(p.id), "objectName": "VoucherPos", "mapAll": True,
        "accountingType": {"id": int(kategorie_id or p.kategorie_id), "objectName": "AccountingType"},
        "taxRate": float(p.steuersatz), "sumGross": float(bank), "net": False,
    }], "voucherPosDelete": None}


def neuer_beleg_body(umsatz: Umsatz, regel: Standardregel, kategorie_id: str) -> dict:
    betrag = abs(umsatz.betrag)
    return {
        "voucher": {
            "objectName": "Voucher", "mapAll": True, "status": 100,
            "voucherDate": umsatz.datum.isoformat(), "supplierName": regel.lieferant,
            "description": f"{regel.name} {umsatz.datum:%m/%Y}",
            "taxType": "default", "creditDebit": "D" if umsatz.betrag > 0 else "C", "voucherType": "VOU",
        },
        "voucherPosSave": [{
            "objectName": "VoucherPos", "mapAll": True,
            "accountingType": {"id": int(kategorie_id), "objectName": "AccountingType"},
            "taxRate": 0, "sumGross": float(betrag), "net": False,
        }],
        "voucherPosDelete": None,
    }


class Schreiber:
    def __init__(self, client, conn, run_id: int, dry_run: bool, limit: int):
        self.client, self.conn, self.run_id = client, conn, run_id
        self.dry_run, self.limit = dry_run, limit
        self.zaehler = 0                 # begonnene Fälle (auch abgebrochene) — Limit zählt Versuche
        self.benutzte_umsaetze: set[str] = set()
        self._geschrieben = False

    def _schreibe(self, methode: str, pfad: str, body: dict, objekt_typ: str, objekt_id: str, aktion: str):
        if not any(m == methode and p.match(pfad) for m, p in ERLAUBT):
            raise RegelVerletzung(f"Schreibpfad nicht erlaubt: {pfad}")
        aid = db.log_geplant(self.conn, self.run_id, objekt_typ, objekt_id, aktion, body, self.dry_run)
        if self.dry_run:
            db.log_ergebnis(self.conn, aid, "dry-run")
            return None
        self._geschrieben = True         # auch bei Fehler: Request kann verarbeitet worden sein
        try:
            res = getattr(self.client, methode)(pfad, json=body)
        except Exception as e:
            db.log_ergebnis(self.conn, aid, "fehler", str(e))
            raise Abbruch(f"{aktion} fehlgeschlagen: {e}") from e
        db.log_ergebnis(self.conn, aid, "ok")
        return res

    @staticmethod
    def _pruefe_datum(*daten) -> None:
        for d in daten:
            if d is None or d < STICHTAG:
                raise RegelVerletzung(f"Datum {d} vor Stichtag {STICHTAG}")

    def _pruefe_limit(self) -> None:
        if self.zaehler >= self.limit:
            raise LimitErreicht(f"Limit {self.limit} erreicht")

    def _nachlesen(self, beleg_id: str, kategorie_id: str, brutto: Decimal, waehrung: str = "EUR") -> None:
        try:
            v = self.client.get(f"Voucher/{beleg_id}")["objects"][0]
            pos = self.client.get("VoucherPos", params={"voucher[id]": beleg_id,
                                                        "voucher[objectName]": "Voucher"})["objects"]
            ok = (int(v["status"]) == 100 and Decimal(str(v["sumGross"])) == brutto
                  and (v.get("currency") or "EUR") == waehrung
                  and pos and all(str(p["accountingType"]["id"]) == str(kategorie_id) for p in pos))
        except Exception as e:
            raise Abbruch(f"Nachlesen fehlgeschlagen (Beleg {beleg_id}): {e}") from e
        if not ok:
            raise Abbruch(f"Nachlesen weicht ab (Beleg {beleg_id})")

    def ausfuehren(self, fall: Fall, kategorie_id: str | None = None) -> str:
        self._pruefe_limit()
        if fall.umsatz is not None and fall.umsatz.id in self.benutzte_umsaetze:
            raise Abbruch(f"Umsatz {fall.umsatz.id} in diesem Lauf bereits verwendet")
        self.zaehler += 1
        self._geschrieben = False
        try:
            if fall.art == "beleg":
                ergebnis = self._beleg(fall)
            elif fall.art == "rechnung":
                ergebnis = self._rechnung(fall)
            elif fall.art == "standard":
                ergebnis = self._standard(fall, kategorie_id or fall.korrektur.get("kategorie_id")
                                          or fall.regel.kategorie_id)
            else:
                raise Abbruch(f"Fallart {fall.art} nicht ausführbar")
        except Abbruch as e:
            if self._geschrieben and not isinstance(e, AbbruchNachSchreiben):
                raise AbbruchNachSchreiben(str(e)) from e
            raise
        finally:
            if self._geschrieben and fall.umsatz is not None:
                self.benutzte_umsaetze.add(fall.umsatz.id)
        if fall.umsatz is not None:
            self.benutzte_umsaetze.add(fall.umsatz.id)
        return ergebnis

    def _beleg(self, fall: Fall) -> str:
        b, u = fall.beleg, fall.umsatz
        if b.waehrung != "EUR":
            if b.waehrung == "USD" and "auf_eur" in fall.korrektur:
                return self._usd_intern(b, u, fall.korrektur.get("kategorie_id", b.kategorie_id), fall.korrektur["auf_eur"])
            raise RegelVerletzung(f"Beleg {b.id}: Fremdwährung {b.waehrung} ohne EUR-Umstellung — kein Schreiben")
        self._pruefe_datum(b.datum, u.datum)
        kat = fall.korrektur.get("kategorie_id", b.kategorie_id)
        brutto = fall.korrektur.get("brutto_eur", b.brutto_eur)
        if fall.korrektur and len(b.positionen) != 1:
            raise Abbruch("Korrektur nur bei genau einer Position")
        if kat is None:
            raise Abbruch("Kategorie fehlt oder nicht eindeutig")
        if fall.korrektur or b.status == 50:
            self._schreibe("post", "Voucher/Factory/saveVoucher", beleg_speichern_body(b, kat, brutto),
                           "Voucher", b.id, "korrigieren+öffnen")
            if not self.dry_run:
                self._nachlesen(b.id, kat, brutto)
        self._schreibe("put", f"Voucher/{b.id}/bookAmount", zuordnen_body(u, brutto), "Voucher", b.id, "zuordnen")
        return "ok"

    def _rechnung(self, fall: Fall) -> str:
        r, u = fall.rechnung, fall.umsatz
        self._pruefe_datum(r.datum, u.datum)
        self._schreibe("put", f"Invoice/{r.id}/bookAmount", zuordnen_body(u, u.betrag), "Invoice", r.id, "zuordnen")
        return "ok"

    def _standard(self, fall: Fall, kategorie_id: str) -> str:
        u = fall.umsatz
        self._pruefe_datum(u.datum)
        betrag = abs(u.betrag)
        res = self._schreibe("post", "Voucher/Factory/saveVoucher", neuer_beleg_body(u, fall.regel, kategorie_id),
                             "Voucher", "neu", "anlegen")
        try:
            beleg_id = "0" if self.dry_run else str(res["objects"]["voucher"]["id"])
        except (KeyError, TypeError) as e:
            raise Abbruch(f"Unerwartete Antwort beim Anlegen: {e}") from e
        if not self.dry_run:
            self._nachlesen(beleg_id, kategorie_id, betrag)
        self._schreibe("put", f"Voucher/{beleg_id}/bookAmount", zuordnen_body(u, betrag), "Voucher", beleg_id, "zuordnen")
        return "ok"

    def loesche_duplikat(self, dup: Beleg, behalten: Beleg) -> None:
        """Löscht einen Entwurf, der ein echtes Duplikat von `behalten` ist. Einzige erlaubte Löschung."""
        gleich = (dup.id != behalten.id and dup.status == 50 and dup.belegnr and dup.belegnr == behalten.belegnr
                  and norm(dup.lieferant) == norm(behalten.lieferant) and dup.brutto_eur == behalten.brutto_eur
                  and dup.datum == behalten.datum)
        if not gleich:
            raise RegelVerletzung(f"Beleg {dup.id} ist kein löschbares Duplikat von {behalten.id}")
        self._pruefe_datum(dup.datum)
        self._schreibe("delete", f"Voucher/{dup.id}", {}, "Voucher", dup.id, f"duplikat löschen (behalten {behalten.id})")

    def usd_auf_eur(self, beleg: Beleg, umsatz: Umsatz) -> None:
        """USD-Beleg auf EUR = Bankbetrag umstellen, nachlesen, zuordnen. Nur per CLI-Befehl nach Einzel-Freigabe."""
        self._geschrieben = False
        try:
            self._usd_intern(beleg, umsatz, beleg.kategorie_id, -umsatz.betrag)
        except Abbruch as e:
            if self._geschrieben and not isinstance(e, AbbruchNachSchreiben):
                raise AbbruchNachSchreiben(str(e)) from e
            raise

    def _usd_intern(self, beleg: Beleg, umsatz: Umsatz, kategorie_id: str | None, bank: Decimal) -> str:
        if not (beleg.waehrung == "USD" and beleg.status in (50, 100) and len(beleg.positionen) == 1
                and kategorie_id and umsatz.betrag < 0 and bank == -umsatz.betrag):
            raise RegelVerletzung(f"Beleg {beleg.id} / Umsatz {umsatz.id}: Umstellung USD->EUR nicht zulässig")
        self._pruefe_datum(beleg.datum, umsatz.datum)
        self._schreibe("post", "Voucher/Factory/saveVoucher", usd_auf_eur_body(beleg, bank, kategorie_id),
                       "Voucher", beleg.id, "usd->eur")
        if not self.dry_run:
            self._nachlesen(beleg.id, kategorie_id, bank, "EUR")
        self._schreibe("put", f"Voucher/{beleg.id}/bookAmount", zuordnen_body(umsatz, bank),
                       "Voucher", beleg.id, "zuordnen")
        return "ok"
