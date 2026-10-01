"""Gemeinsamer sevDesk-REST-Client. Base-URL/Auth laut sevdesk-mcp Referenz (Bearer Token)."""
import requests

BASE_URL = "https://my.sevdesk.de/api/v1"


class SevdeskClient:
    def __init__(self, api_token: str):
        self._session = requests.Session()
        self._session.headers.update({"Authorization": api_token})

    def get(self, path: str, params: dict | None = None) -> dict:
        response = self._session.get(f"{BASE_URL}/{path}", params=params)
        response.raise_for_status()
        return response.json()

    def post(self, path: str, json: dict | None = None) -> dict:
        response = self._session.post(f"{BASE_URL}/{path}", json=json)
        response.raise_for_status()
        return response.json()

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
