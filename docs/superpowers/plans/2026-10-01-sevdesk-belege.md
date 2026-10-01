# sevdesk-belege Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cockpit-Modul, das sevDesk-Belegentwürfe prüft/korrigiert und Zahlungen zuordnet, Ausgangsrechnungen Zahlungseingänge zuordnet und Umsätze ohne Dokument per Standardbuchung erledigt — sichere Fälle automatisch, Rest per Review.

**Architecture:** Reine Logik (`rules.py`) auf Datenklassen (`modell.py`), gespeist von einem Nur-Lese-Loader (`laden.py`). Alle Schreibzugriffe gebündelt in `actions.py` mit Whitelist-Guard, Dry-Run und Protokoll (`db.py`, SQLite). `cli.py` orchestriert `run`, `review`, `status`, `init-regeln`.

**Tech Stack:** Python 3 (python.org-Framework-Python), `requests`, `sqlite3`, `pytest` 9.x, macOS `security` (Keychain).

**Spec:** `docs/superpowers/specs/2026-10-01-sevdesk-belege-design.md`

## Global Constraints

- Nur Objekte mit Datum ≥ 2025-01-01 (`STICHTAG`), Abarbeitung neu → alt.
- Ausgangsrechnungen/Gutschriften/Storno: einziger erlaubter Schreibpfad `Invoice/{id}/bookAmount`.
- Erlaubte Schreibpfade gesamt: `Voucher/Factory/saveVoucher`, `Voucher/{id}/bookAmount`, `Invoice/{id}/bookAmount`. Alles andere → `RegelVerletzung`, Lauf stoppt.
- Beleg erst zuordnen, nachdem Korrektur geschrieben und per Re-Read bestätigt ist.
- Nie löschen.
- Token nur aus Keychain-Service `ww-gf-cockpit-sevdesk`, nie loggen/ausgeben/speichern.
- Grenzwerte (Default): `usd_toleranz_prozent=3`, `tage_vorher=5`, `tage_nachher=45`, `max_betrag=2000`, `min_historie=2`, `lohn_toleranz_prozent=10`, `gebuehren_max=100`.
- `run` Default `--limit 20` Buchungen pro Lauf.
- Kein Git-Repo im Projekt → Commit-Schritte entfallen; stattdessen nach jedem Task `python3 -m pytest` grün.
- Tests laufen aus Modulordner: `cd sevdesk-belege && python3 -m pytest -q`.

## Review Focus

1. Ein Umsatz wird von einem Beleg-Review-Fall beansprucht und darf nicht zusätzlich als Standardbuchung oder Rechnungszahlung „sicher“ werden → Test `test_umsatz_nur_einmal_vergeben` (Task 4).
2. sevDesk rechnet USD-Beleg nach dem Speichern selbst neu um → Re-Read weicht ab → nie zuordnen → Test `test_nachlesen_abweichend_kein_zuordnen` (Task 6).
3. Wiederholungslauf nach Teilfehler (Beleg schon offen, nicht zugeordnet) → kein erneutes Speichern ohne Korrektur, nur Zuordnen → Test `test_offener_beleg_ohne_korrektur_nur_zuordnen` (Task 6).
4. Limit erreicht → kein weiterer Schreibvorgang, auch kein `saveVoucher` → Test `test_limit_stoppt_vor_schreiben` (Task 6).
5. Umsatz mit leerem Namen/Zweck oder Betrag 0 → kein Absturz, landet in „ohne_beleg“ → Test `test_umsatz_leer_kein_absturz` (Task 4).

---

## File Structure

| Datei | Verantwortung |
|---|---|
| `shared/keychain.py` (neu) | `keychain_token(service)` (Name `keychain` statt `secrets`, um stdlib-Modul nicht zu überdecken) |
| `shared/sevdesk_client.py` (ändern) | `put`, Retry 429/5xx |
| `sevdesk-mahnwesen/cli.py` (ändern) | Token aus Keychain |
| `sevdesk-belege/modell.py` | Datenklassen, `STICHTAG`, `Grenzen` |
| `sevdesk-belege/rules.py` | reine Logik |
| `sevdesk-belege/laden.py` | GET + Parsing |
| `sevdesk-belege/db.py` | SQLite Schema + Protokoll/Review |
| `sevdesk-belege/actions.py` | Schreibzugriffe, Guards |
| `sevdesk-belege/cli.py` | Befehle |
| `sevdesk-belege/config.ini.example`, `standardbuchungen.json` (generiert), `CLAUDE.md` | Konfig/Doku |
| `sevdesk-belege/tests/` | `conftest.py`, `test_shared.py`, `test_rules.py`, `test_laden.py`, `test_db.py`, `test_actions.py` |

---

### Task 1: Shared — Keychain-Token, Client `put` + Retry, Mahnwesen umstellen

**Files:**
- Create: `shared/keychain.py`
- Modify: `shared/sevdesk_client.py`
- Modify: `sevdesk-mahnwesen/cli.py` (`build_client`)
- Create: `sevdesk-belege/tests/conftest.py`, `sevdesk-belege/tests/test_shared.py`

**Interfaces:**
- Produces: `shared.keychain.keychain_token(service: str) -> str`; `SevdeskClient(api_token).get(path, params=None) -> dict`, `.post(path, json=None) -> dict`, `.put(path, json=None) -> dict`.

- [ ] **Step 1: Abhängigkeit installieren**

Run: `python3 -m pip install requests`
Expected: `Successfully installed requests…` oder `Requirement already satisfied`.

- [ ] **Step 2: conftest + failing tests**

`sevdesk-belege/tests/conftest.py`:
```python
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

MODUL = Path(__file__).parent.parent
sys.path.insert(0, str(MODUL))
sys.path.insert(0, str(MODUL.parent))

HEUTE = date(2026, 10, 1)


def D(x) -> Decimal:
    return Decimal(str(x))
```

`sevdesk-belege/tests/test_shared.py`:
```python
import subprocess

import pytest

from shared import keychain, sevdesk_client


def test_keychain_token_liest_service(monkeypatch):
    def fake_run(cmd, capture_output, text):
        assert cmd == ["security", "find-generic-password", "-s", "svc", "-w"]
        return subprocess.CompletedProcess(cmd, 0, stdout="abc123\n", stderr="")
    monkeypatch.setattr(keychain.subprocess, "run", fake_run)
    assert keychain.keychain_token("svc") == "abc123"


def test_keychain_token_fehlt(monkeypatch):
    monkeypatch.setattr(keychain.subprocess, "run",
                        lambda cmd, capture_output, text: subprocess.CompletedProcess(cmd, 44, stdout="", stderr="x"))
    with pytest.raises(RuntimeError, match="security add-generic-password"):
        keychain.keychain_token("svc")


class FakeResp:
    def __init__(self, status, body=None):
        self.status_code = status
        self._body = body or {}

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_retry_bei_429(monkeypatch):
    client = sevdesk_client.SevdeskClient("t")
    antworten = [FakeResp(429), FakeResp(200, {"objects": [1]})]
    monkeypatch.setattr(client._session, "request", lambda *a, **k: antworten.pop(0))
    monkeypatch.setattr(sevdesk_client.time, "sleep", lambda s: None)
    assert client.get("Voucher") == {"objects": [1]}


def test_put_gibt_json(monkeypatch):
    client = sevdesk_client.SevdeskClient("t")
    gesehen = {}

    def fake_request(method, url, **kw):
        gesehen.update(method=method, url=url, json=kw.get("json"))
        return FakeResp(200, {"objects": {"ok": True}})
    monkeypatch.setattr(client._session, "request", fake_request)
    assert client.put("Voucher/1/bookAmount", json={"a": 1}) == {"objects": {"ok": True}}
    assert gesehen == {"method": "PUT", "url": f"{sevdesk_client.BASE_URL}/Voucher/1/bookAmount", "json": {"a": 1}}


def test_retry_gibt_nach_3_versuchen_auf(monkeypatch):
    client = sevdesk_client.SevdeskClient("t")
    monkeypatch.setattr(client._session, "request", lambda *a, **k: FakeResp(503))
    monkeypatch.setattr(sevdesk_client.time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError, match="HTTP 503"):
        client.get("Voucher")
```

- [ ] **Step 3: Tests laufen lassen → FAIL**

Run: `cd sevdesk-belege && python3 -m pytest tests/test_shared.py -q`
Expected: FAIL (`ImportError: cannot import name 'keychain'`).

- [ ] **Step 4: Implementierung**

`shared/keychain.py`:
```python
"""Liest Secrets aus der macOS Keychain (security CLI). Gibt Token nie aus."""
import subprocess


def keychain_token(service: str) -> str:
    result = subprocess.run(["security", "find-generic-password", "-s", service, "-w"],
                            capture_output=True, text=True)
    token = result.stdout.strip()
    if result.returncode != 0 or not token:
        raise RuntimeError(
            f"Kein Keychain-Eintrag '{service}'. Anlegen: "
            f"security add-generic-password -s {service} -a sevdesk -w"
        )
    return token
```

`shared/sevdesk_client.py` — `get`/`post` durch gemeinsames `_request` ersetzen, `put` ergänzen, Rest unverändert:
```python
"""Gemeinsamer sevDesk-REST-Client. Base-URL/Auth laut sevdesk-mcp Referenz (Bearer Token)."""
import time

import requests

BASE_URL = "https://my.sevdesk.de/api/v1"
RETRY_STATUS = {429, 500, 502, 503, 504}
VERSUCHE = 3


class SevdeskClient:
    def __init__(self, api_token: str):
        self._session = requests.Session()
        self._session.headers.update({"Authorization": api_token})

    def _request(self, method: str, path: str, **kwargs) -> dict:
        for versuch in range(VERSUCHE):
            response = self._session.request(method, f"{BASE_URL}/{path}", timeout=60, **kwargs)
            if response.status_code not in RETRY_STATUS or versuch == VERSUCHE - 1:
                break
            time.sleep(2 ** versuch)
        response.raise_for_status()
        return response.json()

    def get(self, path: str, params: dict | None = None) -> dict:
        return self._request("GET", path, params=params)

    def post(self, path: str, json: dict | None = None) -> dict:
        return self._request("POST", path, json=json)

    def put(self, path: str, json: dict | None = None) -> dict:
        return self._request("PUT", path, json=json)
```
(`get_open_invoices` und `add_tag_to_invoice` bleiben darunter unverändert.)

`test_put_gibt_json` prüft `kw.get("json")`; `timeout` kommt zusätzlich in `kw` — passt.

`sevdesk-mahnwesen/cli.py`:
```python
from shared.keychain import keychain_token
...
def build_client(config) -> SevdeskClient:
    return SevdeskClient(keychain_token("ww-gf-cockpit-sevdesk"))
```
Und in `sevdesk-mahnwesen/CLAUDE.md` Setup-Schritt 1: `api_token` aus `config.ini` streichen, stattdessen Keychain-Befehl `security add-generic-password -s ww-gf-cockpit-sevdesk -a sevdesk -w`. `config.ini.example` dort: `[sevdesk]`-Abschnitt entfernen.

- [ ] **Step 5: Tests → PASS**

Run: `cd sevdesk-belege && python3 -m pytest tests/test_shared.py -q`
Expected: `5 passed`.

---

### Task 2: Modell + Basis-Regeln (Stichtag, Normalisierung, Duplikate, Lernen)

**Files:**
- Create: `sevdesk-belege/modell.py`, `sevdesk-belege/rules.py`
- Test: `sevdesk-belege/tests/test_rules.py`

**Interfaces:**
- Produces (`modell.py`): `STICHTAG`, `Umsatz`, `Position`, `Beleg` (Properties `kategorie_id`, `steuer`), `Rechnung`, `Grenzen`, `LieferantWissen`, `Standardregel`, `Fall`.
- Produces (`rules.py`): `norm(text) -> str`, `name_passt(lieferant, umsatz) -> bool`, `ab_stichtag(objekte, heute) -> list` (Objekte mit `.datum`), `duplikate(belege) -> set[str]`, `lerne(historie, grenzen) -> dict[str, LieferantWissen]`.

- [ ] **Step 1: Test-Factories + failing tests**

`sevdesk-belege/tests/test_rules.py` (Kopf, wird in Task 3–5 erweitert):
```python
from datetime import date, timedelta
from decimal import Decimal

import rules
from conftest import HEUTE, D
from modell import Beleg, Grenzen, Position, Rechnung, Standardregel, Umsatz

G = Grenzen()


def umsatz(id="u1", datum=date(2026, 9, 10), betrag="-49.99", name="Hetzner Online GmbH", zweck="Rechnung R123", konto="1"):
    return Umsatz(id=id, konto_id=konto, datum=datum, betrag=D(betrag), name=name, zweck=zweck)


def beleg(id="b1", datum=date(2026, 9, 8), lieferant="Hetzner Online GmbH", brutto="49.99", fremd=None,
          waehrung="EUR", status=50, steuerart="default", kat="2819", satz="19", positionen=None, dok=True):
    pos = positionen if positionen is not None else (Position(id=f"p{id}", kategorie_id=kat, steuersatz=D(satz), brutto=D(brutto)),)
    return Beleg(id=id, datum=datum, lieferant=lieferant, brutto_eur=D(brutto),
                 brutto_fremd=D(fremd) if fremd else None, waehrung=waehrung, status=status,
                 steuerart=steuerart, positionen=pos, hat_dokument=dok)


def historie(lieferant="Hetzner Online GmbH", kat="2819", satz="19", n=2, brutto="49.99", dok=True, start=date(2025, 3, 1)):
    return [beleg(id=f"h{lieferant}{i}", datum=start + timedelta(days=30 * i), lieferant=lieferant,
                  kat=kat, satz=satz, brutto=brutto, status=1000, dok=dok) for i in range(n)]


def test_norm_entfernt_rechtsform_und_sonderzeichen():
    assert rules.norm("Hetzner Online GmbH & Co. KG") == "hetzner online"


def test_name_passt_unscharf():
    assert rules.name_passt("Hetzner Online GmbH", umsatz(name="HETZNER ONLINE"))
    assert rules.name_passt("Bitwarden Inc.", umsatz(name="", zweck="PAYPAL *BITWARDEN 4029357733"))
    assert not rules.name_passt("Hetzner Online GmbH", umsatz(name="Google Ireland", zweck="Workspace"))


def test_name_passt_kurze_tokens_zaehlen_nicht():
    assert not rules.name_passt("A&O", umsatz(name="A und O Hotels"))


def test_ab_stichtag_filtert_und_sortiert_neu_nach_alt():
    alt = umsatz(id="alt", datum=date(2024, 12, 31))
    a = umsatz(id="a", datum=date(2025, 1, 1))
    b = umsatz(id="b", datum=date(2026, 9, 1))
    zukunft = umsatz(id="z", datum=date(2030, 7, 26))
    assert [x.id for x in rules.ab_stichtag([a, alt, zukunft, b], HEUTE)] == ["b", "a"]


def test_ab_stichtag_ohne_datum_raus():
    assert rules.ab_stichtag([beleg(datum=None)], HEUTE) == []


def test_duplikate_gleicher_lieferant_betrag_datum():
    b1, b2, b3 = beleg(id="1"), beleg(id="2"), beleg(id="3", brutto="10")
    assert rules.duplikate([b1, b2, b3]) == {"1", "2"}


def test_lerne_eindeutig():
    w = rules.lerne(historie(), G)
    assert w["hetzner online"].kategorie_id == "2819"
    assert w["hetzner online"].steuer == "default:19"


def test_lerne_zu_wenig_historie():
    assert rules.lerne(historie(n=1), G) == {}


def test_lerne_ausreisser_kategorie_kein_wissen():
    h = historie(n=2) + historie(kat="9999", n=1, start=date(2026, 1, 5))
    assert "hetzner online" not in rules.lerne(h, G)


def test_lerne_ignoriert_vor_stichtag():
    assert rules.lerne(historie(start=date(2024, 1, 1), n=2), G) == {}


def test_lerne_letzter_betrag():
    h = historie(n=1, brutto="100") + historie(n=1, brutto="110", start=date(2026, 8, 1))
    assert rules.lerne(h, G)["hetzner online"].letzter_betrag == D("110")
```

Hinweis zum letzten Test: beide Aufrufe erzeugen ids `hHetzner Online GmbH0` — ids sind für `lerne` irrelevant.

- [ ] **Step 2: Run → FAIL**

Run: `cd sevdesk-belege && python3 -m pytest tests/test_rules.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'rules'`).

- [ ] **Step 3: Implementierung**

`sevdesk-belege/modell.py`:
```python
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
    lohn_toleranz_prozent: Decimal = Decimal("10")
    gebuehren_max: Decimal = Decimal("100")
    standard_kategorie_ids: frozenset[str] = frozenset()


@dataclass(frozen=True)
class LieferantWissen:
    kategorie_id: str
    steuer: str
    letzter_betrag: Decimal


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
```

`steuer` mit `normalize()`: `Decimal("19.00")` und `Decimal("19")` ergeben beide `"19"`; `Decimal("0")` → `"0"`.

`sevdesk-belege/rules.py`:
```python
"""Reine Entscheidungslogik ohne API-Zugriff: prüfen, lernen, Kandidaten, einstufen."""
import re
from collections import defaultdict
from datetime import date

from modell import STICHTAG, Beleg, Grenzen, LieferantWissen, Umsatz

_RECHTSFORM = re.compile(
    r"\b(gmbh|mbh|co|kg|ag|ug|ohg|gbr|ltd|inc|llc|pte|bv|sarl|sarlau|sa|se|ek|ev|uab|oy|ab|plc)\b"
)


def norm(text: str) -> str:
    t = (text or "").lower().replace(".", "")
    t = re.sub(r"[^a-z0-9äöüß]+", " ", t)
    t = _RECHTSFORM.sub(" ", t)
    return " ".join(t.split())


def name_passt(lieferant: str, umsatz: Umsatz) -> bool:
    text = norm(f"{umsatz.name} {umsatz.zweck}")
    tokens = [w for w in norm(lieferant).split() if len(w) >= 4]
    return bool(tokens) and any(w in text for w in tokens)


def ab_stichtag(objekte: list, heute: date) -> list:
    gueltig = [o for o in objekte if o.datum is not None and STICHTAG <= o.datum <= heute]
    return sorted(gueltig, key=lambda o: o.datum, reverse=True)


def duplikate(belege: list[Beleg]) -> set[str]:
    gruppen = defaultdict(list)
    for b in belege:
        gruppen[(norm(b.lieferant), b.brutto_eur, b.datum)].append(b.id)
    return {i for ids in gruppen.values() if len(ids) > 1 for i in ids}


def lerne(historie: list[Beleg], grenzen: Grenzen) -> dict[str, LieferantWissen]:
    gruppen = defaultdict(list)
    for b in historie:
        if b.kategorie_id and b.datum and b.datum >= STICHTAG and norm(b.lieferant):
            gruppen[norm(b.lieferant)].append(b)
    wissen = {}
    for key, bs in gruppen.items():
        if len(bs) < grenzen.min_historie:
            continue
        if len({b.kategorie_id for b in bs}) == 1 and len({b.steuer for b in bs}) == 1:
            letzter = max(bs, key=lambda b: b.datum)
            wissen[key] = LieferantWissen(bs[0].kategorie_id, bs[0].steuer, letzter.brutto_eur)
    return wissen
```

Achtung `norm`: Rechtsform-Entfernung **nach** Sonderzeichen-Ersetzung, damit „Co.“/„S.A.“ als Token erkannt werden (Punkte werden vorher entfernt).

- [ ] **Step 4: Run → PASS**

Run: `cd sevdesk-belege && python3 -m pytest tests/test_rules.py -q`
Expected: alle Tests grün.

---

### Task 3: Beleg ↔ Zahlung — Kandidaten und Bewertung

**Files:**
- Modify: `sevdesk-belege/rules.py`
- Test: `sevdesk-belege/tests/test_rules.py` (anhängen)

**Interfaces:**
- Consumes: Task 2.
- Produces: `abweichung_prozent(a, b) -> Decimal`, `kandidaten_beleg(beleg, umsaetze, grenzen) -> list[Umsatz]`, `bewerte_beleg(beleg, kandidaten, rueck: Counter, wissen, dup_ids, grenzen, heute) -> Fall`.

- [ ] **Step 1: Failing tests anhängen**

```python
from collections import Counter

from modell import Fall

W = rules.lerne(historie(), G)


def bewerte(b, us=None, wissen=W, dup=frozenset(), g=G):
    us = us if us is not None else [umsatz()]
    kand = rules.kandidaten_beleg(b, us, g)
    return rules.bewerte_beleg(b, kand, Counter(u.id for u in kand), wissen, set(dup), g, HEUTE)


def test_beleg_sicher_eur():
    f = bewerte(beleg())
    assert f.sicher and f.umsatz.id == "u1" and f.korrektur == {}


def test_beleg_betrag_cent_abweichung_kein_kandidat():
    f = bewerte(beleg(brutto="50.00"))
    assert not f.sicher and f.grund == "keine passende Zahlung"


def test_beleg_zeitfenster():
    assert bewerte(beleg(datum=date(2026, 9, 15))).sicher          # Zahlung 5 Tage vorher
    assert not bewerte(beleg(datum=date(2026, 9, 16))).sicher      # 6 Tage vorher
    assert bewerte(beleg(datum=date(2026, 7, 27))).sicher          # 45 Tage nachher
    assert not bewerte(beleg(datum=date(2026, 7, 26))).sicher      # 46 Tage nachher


def test_beleg_zwei_kandidaten_review():
    f = bewerte(beleg(), [umsatz(id="u1"), umsatz(id="u2", datum=date(2026, 9, 12))])
    assert not f.sicher and "2 mögliche Zahlungen" in f.grund


def test_beleg_umsatz_passt_zu_mehreren_belegen():
    b = beleg()
    u = umsatz()
    f = rules.bewerte_beleg(b, [u], Counter({u.id: 2}), W, set(), G, HEUTE)
    assert not f.sicher and f.grund == "Zahlung passt zu mehreren Belegen"


def test_beleg_duplikat_review():
    f = bewerte(beleg(), dup={"b1"})
    assert not f.sicher and f.grund == "mögliches Duplikat"


def test_beleg_datum_zukunft_review():
    f = bewerte(beleg(datum=date(2030, 7, 26)))
    assert not f.sicher and "Zukunft" in f.grund


def test_beleg_name_passt_nicht():
    f = bewerte(beleg(), [umsatz(name="Google Ireland", zweck="x")])
    assert not f.sicher and f.grund == "Lieferant nicht im Zahlungstext"


def test_beleg_ueber_max_betrag():
    h = rules.lerne(historie(brutto="2500"), G)
    f = bewerte(beleg(brutto="2500"), [umsatz(betrag="-2500")], wissen=h)
    assert not f.sicher and "Betrag über" in f.grund


def test_beleg_unbekannter_lieferant():
    f = bewerte(beleg(), wissen={})
    assert not f.sicher and f.grund == "Lieferant ohne eindeutige Historie"


def test_beleg_steuer_abweichend():
    f = bewerte(beleg(satz="0"))
    assert not f.sicher and f.grund.startswith("Steuer")


def test_beleg_chf_review():
    f = bewerte(beleg(waehrung="CHF"))
    assert not f.sicher and f.grund == "Währung CHF"


def test_beleg_kategorie_anders_review():
    f = bewerte(beleg(kat="1111"))
    assert not f.sicher and f.grund.startswith("Kategorie")


def test_beleg_standardkategorie_wird_korrigiert():
    g = Grenzen(standard_kategorie_ids=frozenset({"1111"}))
    f = bewerte(beleg(kat="1111"), g=g)
    assert f.sicher and f.korrektur == {"kategorie_id": "2819"}


def test_beleg_korrektur_bei_mehreren_positionen_review():
    g = Grenzen(standard_kategorie_ids=frozenset({"1111"}))
    pos = (Position("p1", "1111", D("19"), D("20")), Position("p2", "1111", D("19"), D("29.99")))
    f = bewerte(beleg(positionen=pos), g=g)
    assert not f.sicher and "mehrere Positionen" in f.grund


def usd_beleg(brutto_eur):
    return beleg(lieferant="Bitwarden Inc.", brutto=brutto_eur, fremd="80", waehrung="USD", satz="0")


W_USD = rules.lerne(historie(lieferant="Bitwarden Inc.", satz="0"), G)


def test_usd_innerhalb_toleranz_wird_angepasst():
    u = umsatz(betrag="-71.82", name="BITWARDEN")        # 71.82 / 69.73 = +2.997 %
    f = bewerte(usd_beleg("69.73"), [u], wissen=W_USD)
    assert f.sicher and f.korrektur == {"brutto_eur": D("71.82")}


def test_usd_ausserhalb_toleranz_kein_kandidat():
    u = umsatz(betrag="-71.83", name="BITWARDEN")        # +3.011 %
    f = bewerte(usd_beleg("69.73"), [u], wissen=W_USD)
    assert not f.sicher and f.grund == "keine passende Zahlung"


def test_usd_exakt_keine_korrektur():
    u = umsatz(betrag="-69.73", name="BITWARDEN")
    f = bewerte(usd_beleg("69.73"), [u], wissen=W_USD)
    assert f.sicher and f.korrektur == {}


def test_eingang_ist_kein_kandidat_fuer_beleg():
    f = bewerte(beleg(), [umsatz(betrag="49.99")])
    assert f.grund == "keine passende Zahlung"
```

- [ ] **Step 2: Run → FAIL**

Run: `cd sevdesk-belege && python3 -m pytest tests/test_rules.py -q`
Expected: FAIL (`AttributeError: module 'rules' has no attribute 'kandidaten_beleg'`).

- [ ] **Step 3: Implementierung in `rules.py` anhängen**

```python
from collections import Counter
from datetime import timedelta
from decimal import Decimal

from modell import Fall


def abweichung_prozent(a: Decimal, b: Decimal) -> Decimal:
    return abs(a - b) / b * 100 if b else Decimal("Infinity")


def kandidaten_beleg(beleg: Beleg, umsaetze: list[Umsatz], grenzen: Grenzen) -> list[Umsatz]:
    if beleg.datum is None:
        return []
    von = beleg.datum - timedelta(days=grenzen.tage_vorher)
    bis = beleg.datum + timedelta(days=grenzen.tage_nachher)
    out = []
    for u in umsaetze:
        if u.betrag >= 0 or not (von <= u.datum <= bis):
            continue
        bank = -u.betrag
        if beleg.waehrung == "USD":
            if abweichung_prozent(bank, beleg.brutto_eur) <= grenzen.usd_toleranz_prozent:
                out.append(u)
        elif bank == beleg.brutto_eur:
            out.append(u)
    return out


def bewerte_beleg(beleg: Beleg, kandidaten: list[Umsatz], rueck: Counter, wissen: dict,
                  dup_ids: set[str], grenzen: Grenzen, heute: date) -> Fall:
    def fall(sicher, grund, u=None, korrektur=None):
        return Fall("beleg", sicher, grund, beleg.datum or heute, umsatz=u, beleg=beleg, korrektur=korrektur or {})

    if beleg.datum is None or beleg.datum > heute:
        return fall(False, "Belegdatum fehlt oder in der Zukunft")
    if beleg.id in dup_ids:
        return fall(False, "mögliches Duplikat")
    if not kandidaten:
        return fall(False, "keine passende Zahlung")
    if len(kandidaten) > 1:
        return fall(False, f"{len(kandidaten)} mögliche Zahlungen", kandidaten[0])
    u = kandidaten[0]
    if rueck[u.id] > 1:
        return fall(False, "Zahlung passt zu mehreren Belegen", u)
    if beleg.waehrung not in ("EUR", "USD"):
        return fall(False, f"Währung {beleg.waehrung}", u)
    if not name_passt(beleg.lieferant, u):
        return fall(False, "Lieferant nicht im Zahlungstext", u)
    bank = -u.betrag
    if bank > grenzen.max_betrag:
        return fall(False, f"Betrag über {grenzen.max_betrag} €", u)
    w = wissen.get(norm(beleg.lieferant))
    if w is None:
        return fall(False, "Lieferant ohne eindeutige Historie", u)
    if w.steuer != beleg.steuer:
        return fall(False, f"Steuer {beleg.steuer} statt {w.steuer}", u)

    korrektur = {}
    ist = beleg.kategorie_id
    if ist != w.kategorie_id:
        if ist is not None and ist not in grenzen.standard_kategorie_ids:
            return fall(False, f"Kategorie {ist} statt gelernt {w.kategorie_id}", u)
        korrektur["kategorie_id"] = w.kategorie_id
    if beleg.waehrung == "USD" and bank != beleg.brutto_eur:
        korrektur["brutto_eur"] = bank
    if korrektur and len(beleg.positionen) != 1:
        return fall(False, "mehrere Positionen, Korrektur nicht eindeutig", u)
    return fall(True, "sicher", u, korrektur)
```

Imports oben in `rules.py` zusammenführen (eine Import-Sektion, nicht doppelt).

- [ ] **Step 4: Run → PASS**

Run: `cd sevdesk-belege && python3 -m pytest tests/test_rules.py -q`
Expected: alle grün.

---

### Task 4: Ausgangsrechnungen, Standardbuchungen, Gesamteinstufung, Bericht

**Files:**
- Modify: `sevdesk-belege/rules.py`
- Test: `sevdesk-belege/tests/test_rules.py` (anhängen)

**Interfaces:**
- Consumes: Task 2–3.
- Produces: `kandidaten_rechnung(rechnung, umsaetze) -> list[Umsatz]`, `bewerte_rechnung(rechnung, kandidaten, rueck) -> Fall`, `passende_regeln(umsatz, regeln) -> list[Standardregel]`, `bewerte_standard(umsatz, regeln, wissen, grenzen) -> Fall`, `einstufen(belege, rechnungen, umsaetze, wissen, regeln, grenzen, heute) -> list[Fall]`, `baue_standardregeln(historie, kategorie_namen: dict[str, str], grenzen) -> list[Standardregel]`, `zusammenfassung(faelle) -> dict[str, tuple[int, Decimal]]`.

- [ ] **Step 1: Failing tests anhängen**

```python
def rechnung(id="r1", nummer="RE-10001", datum=date(2026, 9, 1), typ="RE", status=200, offen="1190.00", kunde="Beispiel Kunde GmbH"):
    return Rechnung(id=id, nummer=nummer, datum=datum, typ=typ, status=status, offen=D(offen), kunde=kunde)


def eingang(**kw):
    base = dict(id="e1", datum=date(2026, 9, 7), betrag="1190.00", name="Beispiel Kunde GmbH", zweck="RE-10001")
    base.update(kw)
    return umsatz(**base)


def bewerte_r(r, us):
    k = rules.kandidaten_rechnung(r, us)
    return rules.bewerte_rechnung(r, k, Counter(u.id for u in k))


def test_rechnung_sicher():
    f = bewerte_r(rechnung(), [eingang()])
    assert f.sicher and f.art == "rechnung" and f.umsatz.id == "e1"


def test_rechnung_ohne_nummer_im_zweck_review():
    f = bewerte_r(rechnung(), [eingang(zweck="Danke")])
    assert not f.sicher and "Rechnungsnummer" in f.grund


def test_rechnung_gutschrift_storno_teilrechnung_review():
    for typ in ("GU", "SR", "TR", "ER"):
        assert not bewerte_r(rechnung(typ=typ), [eingang()]).sicher


def test_rechnung_teilbezahlt_review():
    f = bewerte_r(rechnung(status=750), [eingang()])
    assert not f.sicher and f.grund == "teilbezahlt"


def test_rechnung_zahlung_vor_rechnungsdatum_kein_kandidat():
    assert rules.kandidaten_rechnung(rechnung(datum=date(2026, 9, 8)), [eingang()]) == []


REGELN = [
    Standardregel("Lohn / Gehalt: Max Mustermann", "Max Mustermann", "lohn", "50", "Max Mustermann"),
    Standardregel("Finanzamt Kiel", "Finanzamt Kiel", "finanzamt", "60", "Finanzamt Kiel"),
    Standardregel("Bankgebühren", r"kontof(ü|ue)hrung|entgelt", "gebuehren", "70", "Bank"),
]
W_LOHN = rules.lerne(historie(lieferant="Max Mustermann", kat="50", satz="0", brutto="2000", dok=False), G)


def test_standard_lohn_innerhalb_10_prozent():
    f = rules.bewerte_standard(umsatz(betrag="-2200", name="Max Mustermann", zweck="Gehalt 09"), REGELN, W_LOHN, G)
    assert f.sicher and f.art == "standard" and f.regel.art == "lohn"


def test_standard_lohn_ueber_10_prozent_review():
    f = rules.bewerte_standard(umsatz(betrag="-2201", name="Max Mustermann", zweck="Gehalt"), REGELN, W_LOHN, G)
    assert not f.sicher and "Vormonat" in f.grund


def test_standard_lohn_ohne_historie_review():
    f = rules.bewerte_standard(umsatz(betrag="-2000", name="Max Mustermann", zweck=""), REGELN, {}, G)
    assert not f.sicher and f.grund == "kein Vormonatsbetrag"


def test_standard_finanzamt_immer_review():
    f = rules.bewerte_standard(umsatz(betrag="-50", name="Finanzamt Kiel", zweck="UST VZ 08"), REGELN, {}, G)
    assert not f.sicher and f.art == "standard" and "Finanzamt" in f.grund


def test_standard_gebuehren():
    assert rules.bewerte_standard(umsatz(betrag="-12.50", name="", zweck="Kontoführung 09/2026"), REGELN, {}, G).sicher
    assert not rules.bewerte_standard(umsatz(betrag="-100.01", name="", zweck="Entgelt"), REGELN, {}, G).sicher


def test_standard_mehrere_regeln_review():
    f = rules.bewerte_standard(umsatz(betrag="-5", name="Finanzamt Kiel", zweck="Entgelt"), REGELN, {}, G)
    assert not f.sicher and f.grund == "mehrere Standardregeln passen"


def test_ohne_beleg():
    f = rules.bewerte_standard(umsatz(name="Unbekannt AG", zweck="x"), REGELN, {}, G)
    assert f.art == "ohne_beleg" and not f.sicher


def test_umsatz_leer_kein_absturz():
    f = rules.bewerte_standard(umsatz(betrag="0", name="", zweck=""), REGELN, {}, G)
    assert f.art == "ohne_beleg"


def test_einstufen_reihenfolge_und_zuteilung():
    b = beleg()
    u_beleg = umsatz(id="u1")
    u_rech = eingang()
    u_lohn = umsatz(id="u3", datum=date(2026, 9, 30), betrag="-2000", name="Max Mustermann", zweck="Gehalt")
    u_rest = umsatz(id="u4", datum=date(2026, 9, 20), betrag="-15", name="Unbekannt", zweck="x")
    wissen = {**W, **W_LOHN}
    faelle = rules.einstufen([b], [rechnung()], [u_beleg, u_rech, u_lohn, u_rest], wissen, REGELN, G, HEUTE)
    arten = {(f.art, f.umsatz.id if f.umsatz else None) for f in faelle}
    assert arten == {("beleg", "u1"), ("rechnung", "e1"), ("standard", "u3"), ("ohne_beleg", "u4")}
    assert [f.datum for f in faelle] == sorted((f.datum for f in faelle), reverse=True)


def test_umsatz_nur_einmal_vergeben():
    # Beleg mit unbekanntem Lieferanten -> Review, beansprucht aber u3; Lohnregel darf u3 nicht zusätzlich nehmen
    b = beleg(lieferant="Max Mustermann", brutto="2000", datum=date(2026, 9, 28))
    u = umsatz(id="u3", datum=date(2026, 9, 30), betrag="-2000", name="Max Mustermann", zweck="Gehalt")
    faelle = rules.einstufen([b], [], [u], W_LOHN, REGELN, G, HEUTE)
    assert len([f for f in faelle if f.umsatz and f.umsatz.id == "u3"]) == 1
    assert faelle[0].art == "beleg"


def test_einstufen_beleg_vor_stichtag_ignoriert():
    alt = beleg(datum=date(2024, 12, 30))
    assert rules.einstufen([alt], [], [], W, [], G, HEUTE) == []


def test_baue_standardregeln_filtert_ausreisser():
    namen = {"50": "Lohn / Gehalt", "60": "bezahlte Umsatzsteuer", "70": "Kontoführung / Kartengebühren"}
    h = (historie(lieferant="Max Mustermann", kat="50", satz="0", dok=False)
         + historie(lieferant="Finanzamt Kiel", kat="60", satz="0", dok=False)
         + historie(lieferant="Beispiel Telefon GmbH", kat="60", satz="0", dok=False)   # Ausreißer: USt bei Telefonanbieter
         + historie(lieferant="Hetzner Online GmbH", kat="2819", dok=True))               # hat Dokument -> keine Regel
    regeln = rules.baue_standardregeln(h, namen, G)
    assert {(r.art, r.lieferant) for r in regeln} == {
        ("lohn", "Max Mustermann"), ("finanzamt", "Finanzamt Kiel"), ("gebuehren", "Bank")}


def test_zusammenfassung():
    f1 = Fall("beleg", True, "sicher", HEUTE, umsatz=umsatz(betrag="-10"))
    f2 = Fall("ohne_beleg", False, "kein Beleg gefunden", HEUTE, umsatz=umsatz(betrag="-5"))
    f3 = Fall("beleg", False, "keine passende Zahlung", HEUTE, beleg=beleg(brutto="7"))
    z = rules.zusammenfassung([f1, f2, f3])
    assert z == {"sicher": (1, D("10")), "review": (0, D("0")), "ohne_beleg": (1, D("5")),
                 "beleg_ohne_zahlung": (1, D("7"))}
```

- [ ] **Step 2: Run → FAIL**

Run: `cd sevdesk-belege && python3 -m pytest tests/test_rules.py -q`
Expected: FAIL (`AttributeError: … 'kandidaten_rechnung'`).

- [ ] **Step 3: Implementierung in `rules.py` anhängen**

```python
from modell import Rechnung, Standardregel

ART_NACH_KATEGORIE = {
    "Lohn / Gehalt": "lohn",
    "Krankenkasse": "krankenkasse",
    "Miete / Pacht": "miete",
    "Kontoführung / Kartengebühren": "gebuehren",
    "bezahlte Umsatzsteuer": "finanzamt",
}
GEBUEHREN_MUSTER = r"kontof(ü|ue)hrung|entgelt|geb(ü|ue)hr|kartengeb"


def kandidaten_rechnung(rechnung: Rechnung, umsaetze: list[Umsatz]) -> list[Umsatz]:
    return [u for u in umsaetze if u.betrag > 0 and u.betrag == rechnung.offen and u.datum >= rechnung.datum]


def bewerte_rechnung(rechnung: Rechnung, kandidaten: list[Umsatz], rueck: Counter) -> Fall:
    def fall(sicher, grund, u):
        return Fall("rechnung", sicher, grund, u.datum, umsatz=u, rechnung=rechnung)

    u = kandidaten[0]
    if len(kandidaten) > 1:
        return fall(False, f"{len(kandidaten)} mögliche Zahlungseingänge", u)
    if rueck[u.id] > 1:
        return fall(False, "Zahlung passt zu mehreren Rechnungen", u)
    if rechnung.typ != "RE":
        return fall(False, f"Rechnungstyp {rechnung.typ}", u)
    if rechnung.status != 200:
        return fall(False, "teilbezahlt", u)
    if not rechnung.nummer or rechnung.nummer.lower() not in f"{u.zweck} {u.name}".lower():
        return fall(False, "Rechnungsnummer nicht im Verwendungszweck", u)
    return fall(True, "sicher", u)


def passende_regeln(umsatz: Umsatz, regeln: list[Standardregel]) -> list[Standardregel]:
    text = f"{umsatz.name} {umsatz.zweck}"
    return [r for r in regeln if re.search(r.muster, text, re.IGNORECASE)]


def bewerte_standard(umsatz: Umsatz, regeln: list[Standardregel], wissen: dict, grenzen: Grenzen) -> Fall:
    if umsatz.betrag >= 0:
        grund = "Zahlungseingang ohne passende Rechnung" if umsatz.betrag > 0 else "Betrag 0"
        return Fall("ohne_beleg", False, grund, umsatz.datum, umsatz=umsatz)
    treffer = passende_regeln(umsatz, regeln)
    if not treffer:
        return Fall("ohne_beleg", False, "kein Beleg gefunden", umsatz.datum, umsatz=umsatz)
    regel = treffer[0]

    def fall(sicher, grund):
        return Fall("standard", sicher, grund, umsatz.datum, umsatz=umsatz, regel=regel)

    if len(treffer) > 1:
        return fall(False, "mehrere Standardregeln passen")
    betrag = -umsatz.betrag
    if regel.art == "finanzamt":
        return fall(False, "Finanzamt: Steuerart bestätigen")
    if regel.art == "gebuehren":
        if betrag > grenzen.gebuehren_max:
            return fall(False, f"Gebühr über {grenzen.gebuehren_max} €")
        return fall(True, "Standardbuchung")
    if regel.art in ("lohn", "krankenkasse", "miete"):
        w = wissen.get(norm(regel.lieferant))
        if w is None:
            return fall(False, "kein Vormonatsbetrag")
        abw = abweichung_prozent(betrag, w.letzter_betrag)
        if abw > grenzen.lohn_toleranz_prozent:
            return fall(False, f"Betrag weicht {abw:.0f} % vom Vormonat ab")
        return fall(True, "Standardbuchung")
    return fall(False, f"unbekannte Regelart {regel.art}")


def einstufen(belege, rechnungen, umsaetze, wissen, regeln, grenzen, heute) -> list[Fall]:
    belege = ab_stichtag(belege, heute)
    umsaetze = ab_stichtag(umsaetze, heute)
    faelle, vergeben = [], set()

    dup = duplikate(belege)
    kand = {b.id: kandidaten_beleg(b, umsaetze, grenzen) for b in belege}
    rueck = Counter(u.id for ks in kand.values() for u in ks)
    for b in belege:
        f = bewerte_beleg(b, kand[b.id], rueck, wissen, dup, grenzen, heute)
        faelle.append(f)
        vergeben.update(u.id for u in kand[b.id])

    offen_r = [r for r in rechnungen if r.datum and r.datum >= STICHTAG]
    rest = [u for u in umsaetze if u.id not in vergeben]
    kand_r = {r.id: kandidaten_rechnung(r, rest) for r in offen_r}
    rueck_r = Counter(u.id for ks in kand_r.values() for u in ks)
    for r in offen_r:
        if kand_r[r.id]:
            faelle.append(bewerte_rechnung(r, kand_r[r.id], rueck_r))
            vergeben.update(u.id for u in kand_r[r.id])

    for u in umsaetze:
        if u.id not in vergeben:
            faelle.append(bewerte_standard(u, regeln, wissen, grenzen))

    return sorted(faelle, key=lambda f: f.datum, reverse=True)


def baue_standardregeln(historie: list[Beleg], kategorie_namen: dict[str, str], grenzen: Grenzen) -> list[Standardregel]:
    gruppen = defaultdict(list)
    for b in historie:
        if not b.hat_dokument and b.datum and b.datum >= STICHTAG and norm(b.lieferant):
            gruppen[norm(b.lieferant)].append(b)
    regeln = []
    for key, bs in gruppen.items():
        kats = {b.kategorie_id for b in bs}
        if len(bs) < grenzen.min_historie or len(kats) != 1:
            continue
        kat = kats.pop()
        art = ART_NACH_KATEGORIE.get(kategorie_namen.get(kat, ""))
        if art is None or (art == "finanzamt" and "finanzamt" not in key):
            continue
        lieferant = bs[0].lieferant.strip()
        regeln.append(Standardregel(f"{kategorie_namen[kat]}: {lieferant}", re.escape(lieferant), art, kat, lieferant))
    gebuehren_id = next((i for i, n in kategorie_namen.items() if n == "Kontoführung / Kartengebühren"), None)
    if gebuehren_id:
        regeln.append(Standardregel("Bankgebühren", GEBUEHREN_MUSTER, "gebuehren", gebuehren_id, "Bank"))
    return sorted(regeln, key=lambda r: r.name)


def zusammenfassung(faelle: list[Fall]) -> dict[str, tuple[int, Decimal]]:
    z = {k: [0, Decimal("0")] for k in ("sicher", "review", "ohne_beleg", "beleg_ohne_zahlung")}
    for f in faelle:
        if f.sicher:
            key = "sicher"
        elif f.art == "ohne_beleg":
            key = "ohne_beleg"
        elif f.umsatz is None:
            key = "beleg_ohne_zahlung"
        else:
            key = "review"
        betrag = abs(f.umsatz.betrag) if f.umsatz else f.beleg.brutto_eur
        z[key][0] += 1
        z[key][1] += betrag
    return {k: (n, s) for k, (n, s) in z.items()}
```

Zu `test_umsatz_nur_einmal_vergeben`: Beleg „Mustermann“ hat Kandidat u3 (Betrag gleich, Name passt), aber kein Wissen mit Dokument-Historie? `W_LOHN` enthält Mustermann mit Steuer `default:0`, Beleg hat `satz="19"` → Review „Steuer …“. u3 ist über `kand` vergeben → keine Standardbuchung. Test erwartet genau einen Fall mit u3 (`art == "beleg"`).

- [ ] **Step 4: Run → PASS**

Run: `cd sevdesk-belege && python3 -m pytest tests/test_rules.py -q`
Expected: alle grün.

---

### Task 5: Loader (nur GET) und DB

**Files:**
- Create: `sevdesk-belege/laden.py`, `sevdesk-belege/db.py`
- Test: `sevdesk-belege/tests/test_laden.py`, `sevdesk-belege/tests/test_db.py`

**Interfaces:**
- Consumes: `modell`.
- Produces (`laden.py`): `alle(client, path, params) -> list[dict]`, `parse_umsatz(d) -> Umsatz`, `parse_position(d) -> Position`, `parse_beleg(d, positionen) -> Beleg`, `parse_rechnung(d) -> Rechnung`, `kategorien(client) -> dict[str, str]`, `lade(client) -> Daten` mit `Daten(belege, historie, rechnungen, umsaetze)`.
- Produces (`db.py`): `connect(module_dir) -> sqlite3.Connection` (legt Schema an), `init(conn)`, `run_start(conn, dry_run) -> int`, `run_ende(conn, run_id, zusammenfassung: dict)`, `log_geplant(conn, run_id, objekt_typ, objekt_id, aktion, payload, dry_run) -> int`, `log_ergebnis(conn, action_id, ergebnis, fehler=None)`, `review_merken(conn, fall_art, beleg_id, umsatz_id, grund, status)`, `abgelehnt(conn) -> set[tuple[str, str, str]]`, `letzte_runs(conn, n=5) -> list[sqlite3.Row]`.

- [ ] **Step 1: Failing tests**

`sevdesk-belege/tests/test_laden.py`:
```python
from datetime import date

import laden
from conftest import D


class FakeGet:
    def __init__(self, seiten):
        self.seiten = seiten
        self.aufrufe = []

    def get(self, path, params=None):
        self.aufrufe.append((path, dict(params or {})))
        return {"objects": self.seiten.pop(0)}


def test_alle_paginiert():
    c = FakeGet([[{"id": i} for i in range(1000)], [{"id": "x"}]])
    assert len(laden.alle(c, "Voucher", {"status": 50})) == 1001
    assert c.aufrufe[1][1] == {"status": 50, "limit": 1000, "offset": 1000}


def test_parse_umsatz():
    u = laden.parse_umsatz({"id": 7, "checkAccount": {"id": "1001"}, "valueDate": "2026-09-07T00:00:00+02:00",
                            "amount": "-1500.0", "payeePayerName": None, "paymtPurpose": "STEUERNR"})
    assert (u.id, u.konto_id, u.datum, u.betrag, u.name, u.zweck) == ("7", "1001", date(2026, 9, 7), D("-1500.0"), "", "STEUERNR")


def test_parse_beleg_usd_und_position():
    p = laden.parse_position({"id": "11", "accountingType": {"id": "2819"}, "taxRate": "0", "sumGross": "69.73"})
    b = laden.parse_beleg({"id": "5", "voucherDate": "2026-09-21T00:00:00+02:00", "supplierName": "Bitwarden",
                           "sumGross": "69.73", "sumGrossForeignCurrency": "80", "currency": "USD", "status": "50",
                           "taxType": "default", "document": {"id": "9"}}, [p])
    assert b.waehrung == "USD" and b.brutto_fremd == D("80") and b.status == 50
    assert b.kategorie_id == "2819" and b.steuer == "default:0" and b.hat_dokument


def test_parse_beleg_ohne_dokument_lieferant_aus_supplier():
    b = laden.parse_beleg({"id": "6", "voucherDate": None, "supplier": {"name": "TK"}, "sumGross": "1",
                           "currency": None, "status": "1000", "taxType": "default", "document": None}, [])
    assert b.lieferant == "TK" and b.datum is None and b.waehrung == "EUR" and not b.hat_dokument


def test_parse_rechnung_offener_betrag():
    r = laden.parse_rechnung({"id": "1", "invoiceNumber": "RE-1", "invoiceDate": "2026-09-01T00:00:00+02:00",
                              "invoiceType": "RE", "status": "750", "sumGross": "100", "paidAmount": "40",
                              "contact": {"name": "Kunde A"}})
    assert r.offen == D("60") and r.status == 750 and r.kunde == "Kunde A"
```

`sevdesk-belege/tests/test_db.py`:
```python
import sqlite3

import db


def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    db.init(c)
    return c


def test_protokoll_geplant_dann_ergebnis():
    c = conn()
    run = db.run_start(c, dry_run=True)
    aid = db.log_geplant(c, run, "Voucher", "5", "zuordnen", {"amount": 1.5}, True)
    db.log_ergebnis(c, aid, "dry-run")
    row = c.execute("SELECT * FROM actions").fetchone()
    assert (row["aktion"], row["ergebnis"], row["dry_run"], row["payload_json"]) == ("zuordnen", "dry-run", 1, '{"amount": 1.5}')


def test_review_abgelehnt():
    c = conn()
    db.review_merken(c, "beleg", "5", "7", "Kategorie", "abgelehnt")
    db.review_merken(c, "beleg", "6", "8", "x", "angenommen")
    assert db.abgelehnt(c) == {("beleg", "5", "7")}


def test_run_ende_speichert_zahlen():
    c = conn()
    run = db.run_start(c, dry_run=False)
    db.run_ende(c, run, {"sicher": 3, "review": 2, "ohne_beleg": 1})
    r = db.letzte_runs(c)[0]
    assert (r["erledigt"], r["review"], r["ohne_beleg"], r["dry_run"]) == (3, 2, 1, 0)
```

- [ ] **Step 2: Run → FAIL**

Run: `cd sevdesk-belege && python3 -m pytest tests/test_laden.py tests/test_db.py -q`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implementierung**

`sevdesk-belege/laden.py`:
```python
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
                  betrag=_dec(d["amount"]), name=d.get("payeePayerName") or "", zweck=d.get("paymtPurpose") or "")


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
```

`sevdesk-belege/db.py`:
```python
"""SQLite: Protokoll aller Schreibvorgänge, Läufe, Review-Entscheidungen. Kein Cache von sevDesk-Daten."""
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from shared.db import connect as shared_connect

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs(id INTEGER PRIMARY KEY, start TEXT, ende TEXT, dry_run INTEGER,
    erledigt INTEGER, review INTEGER, ohne_beleg INTEGER);
CREATE TABLE IF NOT EXISTS actions(id INTEGER PRIMARY KEY, run_id INTEGER, ts TEXT, objekt_typ TEXT,
    objekt_id TEXT, aktion TEXT, payload_json TEXT, ergebnis TEXT, fehler TEXT, dry_run INTEGER);
CREATE TABLE IF NOT EXISTS review(id INTEGER PRIMARY KEY, art TEXT, beleg_id TEXT, umsatz_id TEXT,
    grund TEXT, status TEXT, entschieden_am TEXT, UNIQUE(art, beleg_id, umsatz_id));
"""


def _jetzt() -> str:
    return datetime.now().isoformat(timespec="seconds")


def init(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def connect(module_dir: Path) -> sqlite3.Connection:
    conn = shared_connect(module_dir)
    init(conn)
    return conn


def run_start(conn, dry_run: bool) -> int:
    cur = conn.execute("INSERT INTO runs(start, dry_run) VALUES (?, ?)", (_jetzt(), int(dry_run)))
    conn.commit()
    return cur.lastrowid


def run_ende(conn, run_id: int, zahlen: dict) -> None:
    conn.execute("UPDATE runs SET ende=?, erledigt=?, review=?, ohne_beleg=? WHERE id=?",
                 (_jetzt(), zahlen.get("sicher", 0), zahlen.get("review", 0), zahlen.get("ohne_beleg", 0), run_id))
    conn.commit()


def log_geplant(conn, run_id, objekt_typ, objekt_id, aktion, payload, dry_run) -> int:
    cur = conn.execute(
        "INSERT INTO actions(run_id, ts, objekt_typ, objekt_id, aktion, payload_json, ergebnis, dry_run)"
        " VALUES (?, ?, ?, ?, ?, ?, 'geplant', ?)",
        (run_id, _jetzt(), objekt_typ, str(objekt_id), aktion, json.dumps(payload, default=str), int(dry_run)))
    conn.commit()
    return cur.lastrowid


def log_ergebnis(conn, action_id: int, ergebnis: str, fehler: str | None = None) -> None:
    conn.execute("UPDATE actions SET ergebnis=?, fehler=? WHERE id=?", (ergebnis, fehler, action_id))
    conn.commit()


def review_merken(conn, art, beleg_id, umsatz_id, grund, status) -> None:
    conn.execute(
        "INSERT INTO review(art, beleg_id, umsatz_id, grund, status, entschieden_am) VALUES (?, ?, ?, ?, ?, ?)"
        " ON CONFLICT(art, beleg_id, umsatz_id) DO UPDATE SET grund=excluded.grund, status=excluded.status,"
        " entschieden_am=excluded.entschieden_am",
        (art, str(beleg_id or ""), str(umsatz_id or ""), grund, status, _jetzt()))
    conn.commit()


def abgelehnt(conn) -> set[tuple[str, str, str]]:
    rows = conn.execute("SELECT art, beleg_id, umsatz_id FROM review WHERE status='abgelehnt'").fetchall()
    return {(r["art"], r["beleg_id"], r["umsatz_id"]) for r in rows}


def letzte_runs(conn, n: int = 5) -> list:
    return conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (n,)).fetchall()
```

Hinweis: Modul heißt `db`, importiert `shared.db` als `shared_connect` — kein Namenskonflikt, weil `shared` ein Paketpfad ist.

- [ ] **Step 4: Run → PASS**

Run: `cd sevdesk-belege && python3 -m pytest -q`
Expected: alle grün.

---

### Task 6: Schreibzugriffe mit Guards (`actions.py`)

**Files:**
- Create: `sevdesk-belege/actions.py`
- Test: `sevdesk-belege/tests/test_actions.py`

**Interfaces:**
- Consumes: `modell.Fall`, `db.log_geplant/log_ergebnis`.
- Produces: `RegelVerletzung(Exception)`, `Abbruch(Exception)`, `LimitErreicht(Exception)`, `Schreiber(client, conn, run_id, dry_run: bool, limit: int)` mit `.ausfuehren(fall, kategorie_id: str | None = None) -> str`, `.zaehler: int`; Body-Builder `beleg_speichern_body(beleg, kategorie_id, brutto) -> dict`, `neuer_beleg_body(umsatz, regel, kategorie_id) -> dict`, `zuordnen_body(umsatz, betrag) -> dict`.

- [ ] **Step 1: Failing tests**

`sevdesk-belege/tests/test_actions.py`:
```python
import sqlite3
from datetime import date

import pytest

import actions
import db
from conftest import D
from modell import Beleg, Fall, Position, Rechnung, Standardregel, Umsatz


class FakeClient:
    def __init__(self, nachlesen_status=100, nachlesen_brutto="49.99", nachlesen_kat="2819", fehler_bei=None):
        self.calls = []
        self.v = {"status": str(nachlesen_status), "sumGross": nachlesen_brutto}
        self.kat = nachlesen_kat
        self.fehler_bei = fehler_bei

    def get(self, path, params=None):
        self.calls.append(("GET", path))
        if path.startswith("Voucher/"):
            return {"objects": [self.v]}
        return {"objects": [{"accountingType": {"id": self.kat}}]}

    def _write(self, method, path, json):
        self.calls.append((method, path))
        if self.fehler_bei and self.fehler_bei in path:
            raise RuntimeError("HTTP 400")
        return {"objects": {"voucher": {"id": 999}}}

    def post(self, path, json=None):
        return self._write("POST", path, json)

    def put(self, path, json=None):
        return self._write("PUT", path, json)


def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    db.init(c)
    return c


def schreiber(client, dry_run=False, limit=20):
    c = conn()
    return actions.Schreiber(client, c, db.run_start(c, dry_run), dry_run, limit), c


U = Umsatz("77", "1001", date(2026, 9, 10), D("-49.99"), "HETZNER", "R123")
POS = (Position("11", "2819", D("19"), D("49.99")),)


def beleg(status=50, datum=date(2026, 9, 8), positionen=POS):
    return Beleg("5", datum, "Hetzner", D("49.99"), None, "EUR", status, "default", positionen,
                 roh={"id": "5", "objectName": "Voucher", "voucherDate": "2026-09-08", "supplierName": "Hetzner",
                      "creditDebit": "C", "taxType": "default", "voucherType": "VOU", "currency": "EUR"})


def fall_beleg(**kw):
    return Fall("beleg", True, "sicher", date(2026, 9, 8), umsatz=U, beleg=kw.pop("b", beleg()), **kw)


def schreibpfade(client):
    return [(m, p) for m, p in client.calls if m != "GET"]


def test_dry_run_schreibt_nie():
    c = FakeClient()
    s, conn_ = schreiber(c, dry_run=True)
    s.ausfuehren(fall_beleg())
    assert schreibpfade(c) == []
    assert [r["ergebnis"] for r in conn_.execute("SELECT ergebnis FROM actions")] == ["dry-run", "dry-run"]


def test_entwurf_reihenfolge_speichern_nachlesen_zuordnen():
    c = FakeClient()
    s, _ = schreiber(c)
    assert s.ausfuehren(fall_beleg()) == "ok"
    assert c.calls == [("POST", "Voucher/Factory/saveVoucher"), ("GET", "Voucher/5"), ("GET", "VoucherPos"),
                       ("PUT", "Voucher/5/bookAmount")]
    assert s.zaehler == 1


def test_offener_beleg_ohne_korrektur_nur_zuordnen():
    c = FakeClient()
    s, _ = schreiber(c)
    s.ausfuehren(fall_beleg(b=beleg(status=100)))
    assert schreibpfade(c) == [("PUT", "Voucher/5/bookAmount")]


def test_nachlesen_abweichend_kein_zuordnen():
    c = FakeClient(nachlesen_brutto="48.00")
    s, _ = schreiber(c)
    with pytest.raises(actions.Abbruch, match="Nachlesen"):
        s.ausfuehren(fall_beleg(korrektur={"brutto_eur": D("49.99")}))
    assert ("PUT", "Voucher/5/bookAmount") not in c.calls


def test_fehler_beim_speichern_kein_zuordnen():
    c = FakeClient(fehler_bei="saveVoucher")
    s, conn_ = schreiber(c)
    with pytest.raises(actions.Abbruch):
        s.ausfuehren(fall_beleg())
    assert ("PUT", "Voucher/5/bookAmount") not in c.calls
    assert conn_.execute("SELECT ergebnis FROM actions").fetchone()["ergebnis"] == "fehler"


def test_guard_datum_vor_stichtag():
    s, _ = schreiber(FakeClient())
    with pytest.raises(actions.RegelVerletzung):
        s.ausfuehren(fall_beleg(b=beleg(datum=date(2024, 12, 31))))


def test_guard_pfad_whitelist():
    s, _ = schreiber(FakeClient())
    for pfad in ("Invoice/1/changeStatus", "Invoice/1", "Voucher/5", "CheckAccountTransaction/77"):
        with pytest.raises(actions.RegelVerletzung):
            s._schreibe("put", pfad, {}, "X", "1", "test")


def test_korrektur_bei_mehreren_positionen_abbruch():
    pos = (Position("11", "2819", D("19"), D("20")), Position("12", "2819", D("19"), D("29.99")))
    s, _ = schreiber(FakeClient())
    with pytest.raises(actions.Abbruch, match="Position"):
        s.ausfuehren(fall_beleg(b=beleg(positionen=pos), korrektur={"kategorie_id": "2819"}))


def test_limit_stoppt_vor_schreiben():
    c = FakeClient()
    s, _ = schreiber(c, limit=1)
    s.ausfuehren(fall_beleg())
    n = len(c.calls)
    with pytest.raises(actions.LimitErreicht):
        s.ausfuehren(fall_beleg())
    assert len(c.calls) == n


def test_rechnung_nur_bookamount():
    c = FakeClient()
    s, _ = schreiber(c)
    r = Rechnung("31", "RE-10001", date(2026, 9, 1), "RE", 200, D("1190.00"), "Beispiel Kunde")
    e = Umsatz("78", "1002", date(2026, 9, 7), D("1190.00"), "Beispiel Kunde GmbH", "RE-10001")
    s.ausfuehren(Fall("rechnung", True, "sicher", e.datum, umsatz=e, rechnung=r))
    assert c.calls == [("PUT", "Invoice/31/bookAmount")]


def test_standard_anlegen_nachlesen_zuordnen():
    c = FakeClient(nachlesen_brutto="2000", nachlesen_kat="50")
    s, _ = schreiber(c)
    u = Umsatz("79", "1001", date(2026, 9, 30), D("-2000"), "Max Mustermann", "Gehalt")
    r = Standardregel("Lohn", "Mustermann", "lohn", "50", "Max Mustermann")
    s.ausfuehren(Fall("standard", True, "Standardbuchung", u.datum, umsatz=u, regel=r))
    assert schreibpfade(c) == [("POST", "Voucher/Factory/saveVoucher"), ("PUT", "Voucher/999/bookAmount")]


def test_zuordnen_body_betrag_positiv():
    b = actions.zuordnen_body(U, D("49.99"))
    assert b["amount"] == 49.99 and b["checkAccountTransaction"] == {"id": 77, "objectName": "CheckAccountTransaction"}
    assert b["checkAccount"] == {"id": 1001, "objectName": "CheckAccount"} and b["date"] == "2026-09-10"


def test_speichern_body_usd_setzt_kurs():
    b = Beleg("5", date(2026, 9, 21), "Bitwarden", D("69.73"), D("80"), "USD", 50, "default",
              (Position("11", "2819", D("0"), D("69.73")),), roh={"id": "5", "currency": "USD"})
    body = actions.beleg_speichern_body(b, "2819", D("71.82"))
    assert body["voucher"]["status"] == 100 and body["voucher"]["propertyExchangeRate"] == "0.89775"
    assert body["voucherPosSave"][0]["sumGross"] == 71.82
```

(71.82 / 80 = 0.89775.)

- [ ] **Step 2: Run → FAIL**

Run: `cd sevdesk-belege && python3 -m pytest tests/test_actions.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'actions'`).

- [ ] **Step 3: Implementierung**

`sevdesk-belege/actions.py`:
```python
"""Alle Schreibzugriffe auf sevDesk. Guards erzwingen die harten Regeln (siehe CLAUDE.md im Root)."""
import re
from decimal import Decimal

import db
from modell import STICHTAG, Beleg, Fall, Standardregel, Umsatz

ERLAUBT = [re.compile(p) for p in (
    r"^Voucher/Factory/saveVoucher$",
    r"^Voucher/\d+/bookAmount$",
    r"^Invoice/\d+/bookAmount$",
)]
ROH_FELDER = ("id", "objectName", "voucherDate", "supplier", "supplierName", "description", "document",
              "creditDebit", "taxType", "voucherType", "currency", "deliveryDate", "paymentDeadline")


class RegelVerletzung(Exception):
    """Harte Regel verletzt — Lauf muss komplett stoppen."""


class Abbruch(Exception):
    """Dieser Fall wird abgebrochen und kommt zur Prüfung; Lauf geht weiter."""


class LimitErreicht(Exception):
    """Maximale Anzahl Buchungen pro Lauf erreicht."""


def zuordnen_body(umsatz: Umsatz, betrag: Decimal) -> dict:
    return {
        "amount": float(abs(betrag)),
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
        voucher["propertyExchangeRate"] = f"{(brutto / beleg.brutto_fremd).normalize():f}"
    einzel = len(beleg.positionen) == 1
    positionen = [{
        "id": int(p.id), "objectName": "VoucherPos", "mapAll": True,
        "accountingType": {"id": int(kategorie_id if einzel else p.kategorie_id), "objectName": "AccountingType"},
        "taxRate": float(p.steuersatz),
        "sumGross": float(brutto if einzel else p.brutto),
        "net": False,
    } for p in beleg.positionen]
    return {"voucher": voucher, "voucherPosSave": positionen, "voucherPosDelete": None}


def neuer_beleg_body(umsatz: Umsatz, regel: Standardregel, kategorie_id: str) -> dict:
    betrag = -umsatz.betrag
    return {
        "voucher": {
            "objectName": "Voucher", "mapAll": True, "status": 100,
            "voucherDate": umsatz.datum.isoformat(), "supplierName": regel.lieferant,
            "description": f"{regel.name} {umsatz.datum:%m/%Y}",
            "taxType": "default", "creditDebit": "C", "voucherType": "VOU",
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
        self.zaehler = 0

    def _schreibe(self, methode: str, pfad: str, body: dict, objekt_typ: str, objekt_id: str, aktion: str):
        if not any(p.match(pfad) for p in ERLAUBT):
            raise RegelVerletzung(f"Schreibpfad nicht erlaubt: {pfad}")
        aid = db.log_geplant(self.conn, self.run_id, objekt_typ, objekt_id, aktion, body, self.dry_run)
        if self.dry_run:
            db.log_ergebnis(self.conn, aid, "dry-run")
            return None
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

    def _nachlesen(self, beleg_id: str, kategorie_id: str, brutto: Decimal) -> None:
        v = self.client.get(f"Voucher/{beleg_id}")["objects"][0]
        pos = self.client.get("VoucherPos", params={"voucher[id]": beleg_id, "voucher[objectName]": "Voucher"})["objects"]
        ok = (int(v["status"]) == 100 and Decimal(str(v["sumGross"])) == brutto
              and pos and all(str(p["accountingType"]["id"]) == str(kategorie_id) for p in pos))
        if not ok:
            raise Abbruch(f"Nachlesen weicht ab (Beleg {beleg_id})")

    def ausfuehren(self, fall: Fall, kategorie_id: str | None = None) -> str:
        if fall.art == "beleg":
            return self._beleg(fall)
        if fall.art == "rechnung":
            return self._rechnung(fall)
        if fall.art == "standard":
            return self._standard(fall, kategorie_id or fall.regel.kategorie_id)
        raise Abbruch(f"Fallart {fall.art} nicht ausführbar")

    def _beleg(self, fall: Fall) -> str:
        b, u = fall.beleg, fall.umsatz
        self._pruefe_datum(b.datum, u.datum)
        self._pruefe_limit()
        kat = fall.korrektur.get("kategorie_id", b.kategorie_id)
        brutto = fall.korrektur.get("brutto_eur", b.brutto_eur)
        if fall.korrektur and len(b.positionen) != 1:
            raise Abbruch("Korrektur nur bei genau einer Position")
        if fall.korrektur or b.status == 50:
            self._schreibe("post", "Voucher/Factory/saveVoucher", beleg_speichern_body(b, kat, brutto),
                           "Voucher", b.id, "korrigieren+öffnen")
            if not self.dry_run:
                self._nachlesen(b.id, kat, brutto)
        self._schreibe("put", f"Voucher/{b.id}/bookAmount", zuordnen_body(u, brutto), "Voucher", b.id, "zuordnen")
        self.zaehler += 1
        return "ok"

    def _rechnung(self, fall: Fall) -> str:
        r, u = fall.rechnung, fall.umsatz
        self._pruefe_datum(r.datum, u.datum)
        self._pruefe_limit()
        self._schreibe("put", f"Invoice/{r.id}/bookAmount", zuordnen_body(u, u.betrag), "Invoice", r.id, "zuordnen")
        self.zaehler += 1
        return "ok"

    def _standard(self, fall: Fall, kategorie_id: str) -> str:
        u = fall.umsatz
        self._pruefe_datum(u.datum)
        self._pruefe_limit()
        betrag = -u.betrag
        res = self._schreibe("post", "Voucher/Factory/saveVoucher", neuer_beleg_body(u, fall.regel, kategorie_id),
                             "Voucher", "neu", "anlegen")
        beleg_id = "0" if self.dry_run else str(res["objects"]["voucher"]["id"])
        if not self.dry_run:
            self._nachlesen(beleg_id, kategorie_id, betrag)
        self._schreibe("put", f"Voucher/{beleg_id}/bookAmount", zuordnen_body(u, betrag), "Voucher", beleg_id, "zuordnen")
        self.zaehler += 1
        return "ok"
```

Hinweis: In `test_standard_anlegen_nachlesen_zuordnen` vergleicht `_nachlesen` `Decimal("2000") == Decimal("2000")` und Kategorie `"50"` — `FakeClient(nachlesen_kat="50")`.

- [ ] **Step 4: Run → PASS**

Run: `cd sevdesk-belege && python3 -m pytest -q`
Expected: alle grün.

---

### Task 7: CLI, Konfiguration, Doku

**Files:**
- Create: `sevdesk-belege/cli.py`, `sevdesk-belege/config.ini.example`, `sevdesk-belege/CLAUDE.md`, `sevdesk-belege/requirements.txt`
- Modify: `CLAUDE.md` (Root, Teilbereiche-Liste)
- Test: `sevdesk-belege/tests/test_cli.py`

**Interfaces:**
- Consumes: alles aus Task 1–6.
- Produces: `cli.lade_grenzen(config) -> Grenzen`, `cli.lade_regeln(pfad) -> list[Standardregel]`, `cli.speichere_regeln(pfad, regeln)`, `cli.verarbeite(faelle, schreiber, conn) -> dict[str, int]`, `main()`.

- [ ] **Step 1: Failing tests**

`sevdesk-belege/tests/test_cli.py`:
```python
import configparser
import sqlite3
from datetime import date

import actions
import cli
import db
from conftest import D
from modell import Fall, Standardregel, Umsatz


def test_lade_grenzen_aus_config():
    c = configparser.ConfigParser()
    c.read_string("[grenzen]\nmax_betrag = 500\nusd_toleranz_prozent = 2.5\n[kategorien]\nstandard_ids = 1, 2\n")
    g = cli.lade_grenzen(c)
    assert g.max_betrag == D("500") and g.usd_toleranz_prozent == D("2.5") and g.tage_nachher == 45
    assert g.standard_kategorie_ids == frozenset({"1", "2"})


def test_regeln_roundtrip(tmp_path):
    p = tmp_path / "standardbuchungen.json"
    regeln = [Standardregel("Bankgebühren", "entgelt", "gebuehren", "70", "Bank")]
    cli.speichere_regeln(p, regeln)
    assert cli.lade_regeln(p) == regeln


class StubSchreiber:
    def __init__(self, fehler=None, limit_nach=None):
        self.fehler, self.limit_nach, self.n = fehler, limit_nach, 0

    def ausfuehren(self, fall, kategorie_id=None):
        if self.limit_nach is not None and self.n >= self.limit_nach:
            raise actions.LimitErreicht("x")
        self.n += 1
        if self.fehler:
            raise actions.Abbruch(self.fehler)
        return "ok"


def fall(i):
    u = Umsatz(str(i), "1", date(2026, 9, i), D("-1"), "n", "z")
    return Fall("standard", True, "Standardbuchung", u.datum, umsatz=u,
                regel=Standardregel("R", "n", "gebuehren", "70", "Bank"))


def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    db.init(c)
    return c


def test_verarbeite_zaehlt_und_stoppt_bei_limit():
    z = cli.verarbeite([fall(1), fall(2), fall(3)], StubSchreiber(limit_nach=2), conn())
    assert z == {"erledigt": 2, "abgebrochen": 0, "limit": True}


def test_verarbeite_abbruch_kommt_in_review():
    c = conn()
    z = cli.verarbeite([fall(1)], StubSchreiber(fehler="Nachlesen weicht ab"), c)
    assert z == {"erledigt": 0, "abgebrochen": 1, "limit": False}
    assert tuple(c.execute("SELECT status, grund FROM review").fetchone()) == ("offen", "Nachlesen weicht ab")
```

- [ ] **Step 2: Run → FAIL**

Run: `cd sevdesk-belege && python3 -m pytest tests/test_cli.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'cli'`).

- [ ] **Step 3: Implementierung**

`sevdesk-belege/cli.py`:
```python
#!/usr/bin/env python3
"""CLI für sevdesk-belege: run, review, status, init-regeln. Harte Regeln: siehe CLAUDE.md im Root."""
import argparse
import configparser
import json
import sys
from dataclasses import asdict
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from shared.keychain import keychain_token
from shared.sevdesk_client import SevdeskClient

import actions
import db
import laden
import rules
from modell import Fall, Grenzen, Standardregel

MODULE_DIR = Path(__file__).parent
REGELN_PFAD = MODULE_DIR / "standardbuchungen.json"
KEYCHAIN_SERVICE = "ww-gf-cockpit-sevdesk"


def lade_grenzen(config: configparser.ConfigParser) -> Grenzen:
    g = config["grenzen"] if config.has_section("grenzen") else {}
    d = Grenzen()
    ids = config.get("kategorien", "standard_ids", fallback="")
    return Grenzen(
        usd_toleranz_prozent=Decimal(g.get("usd_toleranz_prozent", str(d.usd_toleranz_prozent))),
        tage_vorher=int(g.get("tage_vorher", d.tage_vorher)),
        tage_nachher=int(g.get("tage_nachher", d.tage_nachher)),
        max_betrag=Decimal(g.get("max_betrag", str(d.max_betrag))),
        min_historie=int(g.get("min_historie", d.min_historie)),
        lohn_toleranz_prozent=Decimal(g.get("lohn_toleranz_prozent", str(d.lohn_toleranz_prozent))),
        gebuehren_max=Decimal(g.get("gebuehren_max", str(d.gebuehren_max))),
        standard_kategorie_ids=frozenset(i.strip() for i in ids.split(",") if i.strip()),
    )


def lade_regeln(pfad: Path) -> list[Standardregel]:
    if not pfad.exists():
        return []
    return [Standardregel(**r) for r in json.loads(pfad.read_text(encoding="utf-8"))]


def speichere_regeln(pfad: Path, regeln: list[Standardregel]) -> None:
    pfad.write_text(json.dumps([asdict(r) for r in regeln], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def verarbeite(faelle: list[Fall], schreiber, conn) -> dict:
    z = {"erledigt": 0, "abgebrochen": 0, "limit": False}
    for f in faelle:
        try:
            schreiber.ausfuehren(f)
            z["erledigt"] += 1
        except actions.Abbruch as e:
            z["abgebrochen"] += 1
            db.review_merken(conn, f.art, _beleg_id(f), f.umsatz.id if f.umsatz else "", str(e), "offen")
        except actions.LimitErreicht:
            z["limit"] = True
            break
    return z


def _beleg_id(f: Fall) -> str:
    if f.beleg:
        return f.beleg.id
    if f.rechnung:
        return f.rechnung.id
    return f.regel.name if f.regel else ""


def _config() -> configparser.ConfigParser:
    c = configparser.ConfigParser()
    c.read(MODULE_DIR / "config.ini")
    return c


def _einstufen(client, grenzen):
    daten = laden.lade(client)
    wissen = rules.lerne(daten.historie, grenzen)
    return daten, rules.einstufen(daten.belege, daten.rechnungen, daten.umsaetze, wissen,
                                  lade_regeln(REGELN_PFAD), grenzen, date.today())


def _zeile(f: Fall) -> str:
    u = f.umsatz
    links = f"{f.datum}  {f.art:<10}"
    if f.beleg:
        links += f"  Beleg {f.beleg.id} {f.beleg.lieferant[:28]:<28} {f.beleg.brutto_eur:>10} {f.beleg.waehrung}"
    elif f.rechnung:
        links += f"  {f.rechnung.nummer} {f.rechnung.kunde[:28]:<28} {f.rechnung.offen:>10}"
    elif f.regel:
        links += f"  Regel {f.regel.name[:34]:<34}"
    if u:
        links += f"  ↔ Umsatz {u.id} {u.betrag:>10} {(u.name or u.zweck)[:30]}"
    if f.korrektur:
        links += f"  Korrektur {f.korrektur}"
    return f"{links}  [{f.grund}]"


def cmd_run(args) -> int:
    grenzen = lade_grenzen(_config())
    client = SevdeskClient(keychain_token(KEYCHAIN_SERVICE))
    _, faelle = _einstufen(client, grenzen)
    sicher = [f for f in faelle if f.sicher]
    for f in sicher:
        print(_zeile(f))
    conn = db.connect(MODULE_DIR)
    run_id = db.run_start(conn, args.dry_run)
    schreiber = actions.Schreiber(client, conn, run_id, args.dry_run, args.limit)
    try:
        z = verarbeite(sicher, schreiber, conn)
    except actions.RegelVerletzung as e:
        print(f"STOPP — harte Regel verletzt: {e}")
        return 2
    summe = rules.zusammenfassung(faelle)
    db.run_ende(conn, run_id, {"sicher": z["erledigt"], "review": summe["review"][0], "ohne_beleg": summe["ohne_beleg"][0]})
    modus = "DRY-RUN — nichts geschrieben" if args.dry_run else "geschrieben"
    print(f"\n{modus}: {z['erledigt']} erledigt, {z['abgebrochen']} abgebrochen"
          + (f", Limit {args.limit} erreicht" if z["limit"] else ""))
    for k, (n, s) in summe.items():
        print(f"  {k:<20} {n:>5}  {s:>12.2f} €")
    return 0


def cmd_review(args) -> int:
    grenzen = lade_grenzen(_config())
    client = SevdeskClient(keychain_token(KEYCHAIN_SERVICE))
    kat_namen = laden.kategorien(client)
    _, faelle = _einstufen(client, grenzen)
    conn = db.connect(MODULE_DIR)
    abgelehnt = db.abgelehnt(conn)
    offen = [f for f in faelle if not f.sicher and f.umsatz and f.art in ("beleg", "rechnung", "standard")
             and (f.art, _beleg_id(f), f.umsatz.id) not in abgelehnt]
    run_id = db.run_start(conn, args.dry_run)
    schreiber = actions.Schreiber(client, conn, run_id, args.dry_run, args.limit)
    print(f"{len(offen)} Fälle zur Prüfung. j = übernehmen, n = ablehnen (merken), Enter = überspringen, q = Ende\n")
    for f in offen:
        print(_zeile(f))
        kategorie_id = None
        if f.art == "standard" and f.regel.art == "finanzamt":
            steuer = {i: n for i, n in kat_namen.items() if "steuer" in n.lower()}
            for i, n in sorted(steuer.items(), key=lambda kv: kv[1]):
                print(f"    {i}: {n}")
            kategorie_id = input("  Buchungsart-ID (Enter = überspringen): ").strip() or None
            if kategorie_id is None or kategorie_id not in steuer:
                continue
        antwort = input("  übernehmen? [j/n/Enter/q] ").strip().lower()
        if antwort == "q":
            break
        if antwort == "n":
            db.review_merken(conn, f.art, _beleg_id(f), f.umsatz.id, f.grund, "abgelehnt")
        elif antwort == "j":
            try:
                schreiber.ausfuehren(f, kategorie_id)
                db.review_merken(conn, f.art, _beleg_id(f), f.umsatz.id, f.grund, "angenommen")
                print("  ok")
            except actions.Abbruch as e:
                print(f"  abgebrochen: {e}")
            except actions.LimitErreicht:
                print("  Limit erreicht.")
                break
    return 0


def cmd_status(args) -> int:
    conn = db.connect(MODULE_DIR)
    for r in db.letzte_runs(conn):
        print(f"{r['start']}  {'dry' if r['dry_run'] else 'live'}  erledigt={r['erledigt']} "
              f"review={r['review']} ohne_beleg={r['ohne_beleg']}")
    return 0


def cmd_init_regeln(args) -> int:
    if REGELN_PFAD.exists() and not args.force:
        print(f"{REGELN_PFAD.name} existiert schon. Mit --force überschreiben.")
        return 1
    grenzen = lade_grenzen(_config())
    client = SevdeskClient(keychain_token(KEYCHAIN_SERVICE))
    daten = laden.lade(client)
    regeln = rules.baue_standardregeln(daten.historie, laden.kategorien(client), grenzen)
    speichere_regeln(REGELN_PFAD, regeln)
    print(f"{len(regeln)} Regeln nach {REGELN_PFAD.name} geschrieben. Bitte prüfen.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="sevDesk Belege prüfen, korrigieren, zuordnen")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("run", "review"):
        p = sub.add_parser(name)
        p.add_argument("--dry-run", action="store_true")
        p.add_argument("--limit", type=int, default=20)
    sub.add_parser("status")
    p = sub.add_parser("init-regeln")
    p.add_argument("--force", action="store_true")
    args = parser.parse_args()
    handlers = {"run": cmd_run, "review": cmd_review, "status": cmd_status, "init-regeln": cmd_init_regeln}
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
```

`sevdesk-belege/config.ini.example`:
```ini
; Keine Secrets. Token liegt in macOS Keychain (Service ww-gf-cockpit-sevdesk).
[grenzen]
usd_toleranz_prozent = 3
tage_vorher = 5
tage_nachher = 45
max_betrag = 2000
min_historie = 2
lohn_toleranz_prozent = 10
gebuehren_max = 100

[kategorien]
; AccountingType-IDs, die GetMyInvoices als Platzhalter setzt — gelten als "leer" und werden korrigiert
standard_ids =
```

`sevdesk-belege/requirements.txt`:
```
requests
pytest
```

`sevdesk-belege/CLAUDE.md`:
```markdown
# sevdesk-belege

Belegentwürfe (GetMyInvoices) prüfen/korrigieren und Zahlungen zuordnen, Zahlungseingänge auf Ausgangsrechnungen buchen, Umsätze ohne Dokument per Standardbuchung erledigen. Spec: `../docs/superpowers/specs/2026-10-01-sevdesk-belege-design.md`.

## Setup

1. Token: `security add-generic-password -s ww-gf-cockpit-sevdesk -a sevdesk -w`
2. `cp config.ini.example config.ini` (nur Grenzwerte)
3. `python3 -m pip install -r requirements.txt`
4. `python3 cli.py init-regeln` → `standardbuchungen.json` prüfen/anpassen

## Befehle

    python3 cli.py run --dry-run          # Vorschau, schreibt nichts
    python3 cli.py run --limit 1          # echter Lauf, max. 1 Buchung
    python3 cli.py review [--dry-run]     # unsichere Fälle einzeln entscheiden
    python3 cli.py status                 # letzte Läufe
    python3 cli.py init-regeln [--force]  # Standardbuchungen aus Historie ab 2025 erzeugen

## Architektur

- `modell.py` Datenklassen · `rules.py` reine Logik · `laden.py` nur GET · `actions.py` alle Schreibzugriffe + Guards · `db.py` Protokoll/Review (SQLite `data.db`) · `cli.py`
- Harte Regeln: Root-`CLAUDE.md` → „Harte Regeln sevDesk“. Erlaubte Schreibpfade nur in `actions.ERLAUBT`.

## Tests

    python3 -m pytest -q

## Selflearning

### Lessons
```

Root-`CLAUDE.md`, Abschnitt „Teilbereiche“ ergänzen:
```markdown
- [sevdesk-belege](sevdesk-belege/CLAUDE.md) — Belege prüfen/korrigieren, Zahlungen zuordnen, Standardbuchungen (sevDesk API)
```

- [ ] **Step 4: Run → PASS**

Run: `cd sevdesk-belege && python3 -m pytest -q`
Expected: alle grün.

- [ ] **Step 5: CLI-Smoke ohne API**

Run: `cd sevdesk-belege && python3 cli.py --help && python3 cli.py status`
Expected: Hilfe mit `run, review, status, init-regeln`; `status` ohne Ausgabe, Exit 0.

---

### Task 8: Abnahme lesend — `init-regeln` und Dry-Run gegen echtes sevDesk

**Files:**
- Create (generiert): `sevdesk-belege/standardbuchungen.json`, `sevdesk-belege/config.ini`

**Interfaces:**
- Consumes: CLI aus Task 7. Nur GET gegen sevDesk (Dry-Run).

- [ ] **Step 1: Platzhalter-Kategorie von GetMyInvoices ermitteln (GET)**

Run (Scratchpad-Skript, nur GET): Häufigkeit `accountingType` über alle Positionen der Belegentwürfe ab 2025 ausgeben, mit Namen aus `AccountingType`.
Expected: Top-Kategorien mit Anzahl. Mit Nutzer klären, welche ID(s) GetMyInvoices als Platzhalter setzt → in `config.ini` `[kategorien] standard_ids`.

- [ ] **Step 2: Regeln erzeugen**

Run: `cd sevdesk-belege && cp config.ini.example config.ini && python3 cli.py init-regeln`
Expected: `N Regeln nach standardbuchungen.json geschrieben`. Datei mit Nutzer durchgehen: Lohn-, Krankenkassen-, Miete-, Finanzamt-Regeln plausibel; keine Regel für Ausreißer-Lieferanten.

- [ ] **Step 3: Dry-Run**

Run: `cd sevdesk-belege && python3 cli.py run --dry-run --limit 1000`
Expected: Liste sicherer Fälle + Zusammenfassung; `actions` in `data.db` nur `dry-run`. Mit Nutzer Stichproben prüfen (10 sichere Fälle in sevDesk-Oberfläche nachsehen). Bei falschen „sicher“-Einstufungen: Test in `test_rules.py` ergänzen, Regel fixen, wiederholen.

---

### Task 9: Erster echter Schreiblauf (nur mit Freigabe) und API-Verifikation

**Files:**
- Modify bei Bedarf: `sevdesk-belege/actions.py` (Bodies), `sevdesk-belege/tests/test_actions.py`

**Interfaces:**
- Consumes: alles. **Jeder Schritt mit Schreibzugriff braucht vorher die explizite Freigabe des Nutzers für genau diesen Aufruf.**

- [ ] **Step 1: Kandidat wählen**

Aus Dry-Run einen sicheren **EUR-Entwurf ohne Korrektur** wählen, Nutzer zeigt/bestätigt in sevDesk-Oberfläche.

- [ ] **Step 2: Freigabe einholen, dann `run --limit 1`**

Run (nach Freigabe): `cd sevdesk-belege && python3 cli.py run --limit 1`
Expected: `1 erledigt`. Danach per GET prüfen: Beleg Status 1000, Umsatz Status ≠ 100, Betrag korrekt. Nutzer prüft in sevDesk-Oberfläche.

Falls sevDesk den `saveVoucher`-Body ablehnt (HTTP 400/422): Fehlertext aus `data.db` lesen (`SELECT fehler FROM actions ORDER BY id DESC LIMIT 1`), Body in `beleg_speichern_body` anpassen, Test `test_speichern_body_*` anpassen, `pytest`, erneut Freigabe holen.

- [ ] **Step 3: Gleiches für je einen Fall: USD mit Korrektur, Ausgangsrechnung, Standardbuchung (Lohn)**

Jeweils: Kandidat zeigen → Freigabe → `run`-Lauf auf diesen Fall beschränkt (`--limit 1`, Fall steht oben, weil neu → alt; sonst per `review` gezielt `j`) → GET-Prüfung → Nutzer-Sichtkontrolle. USD: prüfen, dass `sumGross` nach Speichern = Bankbetrag bleibt (sevDesk rechnet nicht zurück); sonst `propertyExchangeRate`-Handling anpassen.

- [ ] **Step 4: Limit schrittweise erhöhen**

Nach Freigabe: `--limit 5`, dann `20`. Nach jedem Lauf `status` + Stichprobe. Erkenntnisse (API-Eigenheiten) als Lessons in `sevdesk-belege/CLAUDE.md`.
