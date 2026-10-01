"""GetMyInvoices Accounts API v3 — nur lesend. Header X-API-KEY, User-Agent mit Konto-ID (Pflicht laut API)."""
import time

import requests

BASE_URL = "https://api.getmyinvoices.com/accounts/v3"
RETRY_STATUS = {429, 500, 502, 503, 504}
VERSUCHE = 3


class GmiClient:
    def __init__(self, api_key: str, konto_id: str):
        self._session = requests.Session()
        self._session.headers.update({"X-API-KEY": api_key, "User-Agent": f"WW-GF-Cockpit {konto_id}",
                                      "Accept": "application/json"})

    def get(self, path: str, params: dict | None = None) -> dict:
        for versuch in range(VERSUCHE):
            r = self._session.request("GET", f"{BASE_URL}/{path}", params=params, timeout=60)
            if r.status_code not in RETRY_STATUS or versuch == VERSUCHE - 1:
                break
            time.sleep(2 ** versuch)
        r.raise_for_status()
        return r.json()

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
