"""Gemeinsamer sevDesk-REST-Client. Base-URL/Auth laut sevdesk-mcp Referenz (Bearer Token)."""
import time

import requests

BASE_URL = "https://my.sevdesk.de/api/v1"
RETRY_STATUS = {429, 500, 502, 503, 504}   # nur GET (idempotent)
RETRY_STATUS_SCHREIBEN = {429}              # POST/PUT: 5xx evtl. schon verarbeitet -> nie wiederholen
VERSUCHE = 3


class SevdeskClient:
    def __init__(self, api_token: str):
        self._session = requests.Session()
        self._session.headers.update({"Authorization": api_token})

    def _request(self, method: str, path: str, **kwargs) -> dict:
        retry = RETRY_STATUS if method == "GET" else RETRY_STATUS_SCHREIBEN
        for versuch in range(VERSUCHE):
            response = self._session.request(method, f"{BASE_URL}/{path}", timeout=60, **kwargs)
            if response.status_code not in retry or versuch == VERSUCHE - 1:
                break
            time.sleep(2 ** versuch)
        response.raise_for_status()
        return response.json() if getattr(response, "content", b"1") else {}

    def get(self, path: str, params: dict | None = None) -> dict:
        return self._request("GET", path, params=params)

    def post(self, path: str, json: dict | None = None) -> dict:
        return self._request("POST", path, json=json)

    def put(self, path: str, json: dict | None = None) -> dict:
        return self._request("PUT", path, json=json)

    def upload(self, path: str, dateiname: str, inhalt: bytes) -> dict:
        return self._request("POST", path, files={"file": (dateiname, inhalt, "application/pdf")})

    def delete(self, path: str, json: dict | None = None) -> dict:
        return self._request("DELETE", path)

    def get_open_invoices(self) -> list[dict]:
        """Rechnungen mit Status 'offen' oder 'teilbezahlt' (sevDesk-Statuscodes 200/1000)."""
        data = self.get("Invoice", params={"status": "200,1000"})
        return data.get("objects", [])

    def add_tag_to_invoice(self, invoice_id: str, tag_name: str) -> dict:
        """Legt Tag an (falls nötig) und verknüpft ihn mit der Rechnung."""
        tags = self.get("Tag", params={"name": tag_name}).get("objects", [])
        tag_id = tags[0]["id"] if tags else self.post("Tag", json={"name": tag_name})["objects"]["id"]
        return self.post(
            "TagRelation",
            json={
                "tag": {"id": tag_id, "objectName": "Tag"},
                "entity": invoice_id,
                "entityObject": "Invoice",
            },
        )
