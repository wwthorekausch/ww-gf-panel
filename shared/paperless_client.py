"""Paperless-ngx REST-Client. Auth: Header 'Authorization: Token <token>'. Löschen ohne Retry."""
import time

import requests

RETRY_STATUS = {429, 500, 502, 503, 504}
VERSUCHE = 3
FELDER = "id,title,content,created,added,original_file_name,correspondent,document_type,tags"


class PaperlessClient:
    def __init__(self, token: str, base_url: str):
        self.base = base_url.rstrip("/")
        self._session = requests.Session()
        self._session.headers.update({"Authorization": f"Token {token}", "Accept": "application/json"})

    def _request(self, method: str, url: str, **kw):
        retry = RETRY_STATUS if method == "GET" else set()
        for versuch in range(VERSUCHE):
            r = self._session.request(method, url, timeout=60, **kw)
            if r.status_code not in retry or versuch == VERSUCHE - 1:
                break
            time.sleep(2 ** versuch)
        r.raise_for_status()
        return r

    def dokumente(self) -> list[dict]:
        url, params, out = f"{self.base}/api/documents/", {"page_size": 100, "fields": FELDER}, []
        while url:
            d = self._request("GET", url, params=params).json()
            out += d.get("results") or []
            url, params = d.get("next"), None      # next enthält die Query schon
        return out

    def dokument(self, doc_id) -> dict:
        return self._request("GET", f"{self.base}/api/documents/{doc_id}/", params={"fields": FELDER}).json()

    def loeschen(self, doc_id) -> None:
        self._request("DELETE", f"{self.base}/api/documents/{doc_id}/")
