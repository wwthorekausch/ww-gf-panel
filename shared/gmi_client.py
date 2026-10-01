"""GetMyInvoices Accounts API v3 — nur lesend. Header X-API-KEY, User-Agent mit Konto-ID (Pflicht laut API)."""
import time

import requests

BASE_URL = "https://api.getmyinvoices.com/accounts/v3"
RETRY_STATUS = {429, 500, 502, 503, 504}
VERSUCHE = 4


class GmiClient:
    def __init__(self, api_key: str, konto_id: str):
        self._session = requests.Session()
        self._session.headers.update({"X-API-KEY": api_key, "User-Agent": f"WW-GF-Cockpit {konto_id}",
                                      "Accept": "application/json"})

    def _roh(self, method: str, path: str, **kw):
        retry = RETRY_STATUS if method == "GET" else {429}
        for versuch in range(VERSUCHE):
            r = self._session.request(method, f"{BASE_URL}/{path}", timeout=60, **kw)
            if r.status_code not in retry or versuch == VERSUCHE - 1:
                break
            time.sleep(10 * (versuch + 1) if r.status_code == 429 else 2 ** versuch)
        r.raise_for_status()
        return r

    def get(self, path: str, params: dict | None = None) -> dict:
        return self._roh("GET", path, params=params).json()

    def dokument(self, uid) -> dict:
        return self.get(f"documents/{uid}", params={"includeDocument": "false", "transactions": "false"})

    def datei(self, uid) -> bytes:
        return self._roh("GET", f"documents/{uid}/file").content

    def put(self, path: str, json: dict) -> dict:
        """Schreibzugriff — nur über actions.Schreiber._gmi_schreibe (Guard: nur Tags)."""
        return self._roh("PUT", path, json=json).json()

    def dokumente(self, start: str, **filter) -> list[dict]:
        out, seite = [], 1
        while True:
            d = self.get("documents", params={"startDateFilter": start, "perPage": 500, "pageNumber": seite,
                                              "archivedFilter": 1, **filter})
            recs = d.get("records") or []
            out += recs if isinstance(recs, list) else list(recs.values())
            if seite >= int(d.get("maxPages") or 1):
                return out
            seite += 1
