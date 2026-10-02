import pytest

from shared import paperless_client


class R:
    def __init__(self, status, body=None):
        self.status_code, self._b, self.content = status, body or {}, b"x"

    def json(self):
        return self._b

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_paginiert_ueber_next(monkeypatch):
    c = paperless_client.PaperlessClient("t", "https://p.example")
    seiten = [R(200, {"results": [{"id": 1}], "next": "https://p.example/api/documents/?page=2"}),
              R(200, {"results": [{"id": 2}], "next": None})]
    urls = []
    monkeypatch.setattr(c._session, "request", lambda m, url, **k: urls.append(url) or seiten.pop(0))
    assert [d["id"] for d in c.dokumente()] == [1, 2]
    assert urls[1] == "https://p.example/api/documents/?page=2"
    assert c._session.headers["Authorization"] == "Token t"


def test_loeschen_kein_retry(monkeypatch):
    c = paperless_client.PaperlessClient("t", "https://p.example")
    aufrufe = []
    monkeypatch.setattr(c._session, "request", lambda m, url, **k: aufrufe.append((m, url)) or R(503))
    with pytest.raises(RuntimeError):
        c.loeschen(7)
    assert aufrufe == [("DELETE", "https://p.example/api/documents/7/")]


def test_patch_nur_erlaubte_felder(monkeypatch):
    c = paperless_client.PaperlessClient("t", "https://p.example")
    monkeypatch.setattr(c._session, "request", lambda m, url, **k: R(200, {"id": 1}))
    c.dokument_patchen(1, {"storage_path": 1, "custom_fields": []})
    with pytest.raises(ValueError):
        c.dokument_patchen(1, {"title": "neu"})


def test_patch_document_type_erlaubt(monkeypatch):
    c = paperless_client.PaperlessClient("t", "https://p.example")
    monkeypatch.setattr(c._session, "request", lambda m, url, **k: R(200, {"id": 1}))
    c.dokument_patchen(1, {"document_type": 6})
