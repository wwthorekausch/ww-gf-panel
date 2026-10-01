"""Datenklassen für sevdesk-belege. Beträge als Decimal; Umsätze: < 0 Ausgang, > 0 Eingang."""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

STICHTAG = date(2025, 1, 1)


@dataclass(frozen=True)
class Umsatz:
    id: str
    konto_id: str
    datum: date
    betrag: Decimal
    name: str
    zweck: str


@dataclass(frozen=True)
class Position:
    id: str
    kategorie_id: str
    steuersatz: Decimal
    brutto: Decimal


@dataclass(frozen=True)
class Beleg:
    id: str
    datum: date | None
    lieferant: str
    brutto_eur: Decimal
    brutto_fremd: Decimal | None
    waehrung: str
    status: int                      # 50 Entwurf, 100 offen, 1000 bezahlt
    steuerart: str
    positionen: tuple[Position, ...]
    hat_dokument: bool = True
    roh: dict = field(default_factory=dict, compare=False, repr=False)

    @property
    def kategorie_id(self) -> str | None:
        ids = {p.kategorie_id for p in self.positionen}
        return ids.pop() if len(ids) == 1 else None

    @property
    def belegnr(self) -> str:
        """Belegnummer, die GetMyInvoices ins Beschreibungsfeld schreibt."""
        return (self.roh.get("description") or "").strip()

    @property
    def steuer(self) -> str:
        return f"{self.steuerart}:" + ",".join(sorted({f"{p.steuersatz.normalize():f}" for p in self.positionen}))


@dataclass(frozen=True)
class Rechnung:
    id: str
    nummer: str
    datum: date
    typ: str                         # RE, ER, TR, SR, GU
    status: int                      # 200 offen, 750 teilbezahlt
    offen: Decimal
    kunde: str


@dataclass(frozen=True)
class Grenzen:
    usd_toleranz_prozent: Decimal = Decimal("3")
    tage_vorher: int = 5
    tage_nachher: int = 45
    max_betrag: Decimal = Decimal("2000")
    min_historie: int = 2
    lohn_toleranz_prozent: Decimal | None = Decimal("10")   # None = keine Vormonatsprüfung
    gebuehren_max: Decimal = Decimal("100")
    tage_eindeutig: int = 5          # mehrere Kandidaten: genau einer in ±N Tagen gewinnt (Monatsabos)
    standard_kategorie_ids: frozenset[str] = frozenset()
    aliase: tuple[tuple[str, str], ...] = ()
    ausgeschlossen: frozenset[str] = frozenset()  # norm(lieferant) — nie buchen (z.B. eigene Umbuchungen)   # (norm(lieferant), norm(alias)) aus config [aliase]


@dataclass(frozen=True)
class LieferantWissen:
    kategorie_id: str
    steuer: str
    letzter_betrag: Decimal
    fest: bool = False               # vom Nutzer festgelegt -> abweichende Kategorie wird korrigiert


@dataclass(frozen=True)
class Standardregel:
    name: str
    muster: str                      # Regex, case-insensitive, auf "name zweck" des Umsatzes
    art: str                         # lohn | krankenkasse | miete | gebuehren | finanzamt
    kategorie_id: str
    lieferant: str


@dataclass
class Fall:
    art: str                         # beleg | rechnung | standard | ohne_beleg
    sicher: bool
    grund: str
    datum: date
    umsatz: Umsatz | None = None
    beleg: Beleg | None = None
    rechnung: Rechnung | None = None
    regel: Standardregel | None = None
    korrektur: dict = field(default_factory=dict)   # {"kategorie_id": str, "brutto_eur": Decimal}
