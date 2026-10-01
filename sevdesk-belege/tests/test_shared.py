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


def test_post_put_kein_retry_bei_5xx(monkeypatch):
    # I1: nicht-idempotente Schreibvorgänge dürfen bei 5xx nicht wiederholt werden
    client = sevdesk_client.SevdeskClient("t")
    aufrufe = []
    monkeypatch.setattr(client._session, "request", lambda *a, **k: aufrufe.append(1) or FakeResp(502))
    monkeypatch.setattr(sevdesk_client.time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError, match="HTTP 502"):
        client.post("Voucher/Factory/saveVoucher", json={})
    assert len(aufrufe) == 1


def test_post_retry_bei_429(monkeypatch):
    client = sevdesk_client.SevdeskClient("t")
    antworten = [FakeResp(429), FakeResp(200, {"objects": 1})]
    monkeypatch.setattr(client._session, "request", lambda *a, **k: antworten.pop(0))
    monkeypatch.setattr(sevdesk_client.time, "sleep", lambda s: None)
    assert client.put("Voucher/1/bookAmount", json={}) == {"objects": 1}


def test_delete_kein_retry_bei_5xx(monkeypatch):
    client = sevdesk_client.SevdeskClient("t")
    aufrufe = []
    monkeypatch.setattr(client._session, "request", lambda m, *a, **k: aufrufe.append(m) or FakeResp(503))
    with pytest.raises(RuntimeError):
        client.delete("Voucher/1")
    assert aufrufe == ["DELETE"]


def test_gmi_client_paginiert_und_header(monkeypatch):
    from shared import gmi_client
    c = gmi_client.GmiClient("k", "G-1")
    assert c._session.headers["X-API-KEY"] == "k" and "G-1" in c._session.headers["User-Agent"]
    seiten = [FakeResp(200, {"maxPages": 2, "records": [{"documentUid": 1}]}),
              FakeResp(200, {"maxPages": 2, "records": [{"documentUid": 2}]})]
    gesehen = []
    monkeypatch.setattr(c._session, "request", lambda m, url, **k: gesehen.append(k["params"]["pageNumber"]) or seiten.pop(0))
    assert [d["documentUid"] for d in c.dokumente("2025-01-01")] == [1, 2] and gesehen == [1, 2]


def test_upload_multipart_kein_retry_5xx(monkeypatch):
    client = sevdesk_client.SevdeskClient("t")
    aufrufe = []
    def fake(m, url, **k):
        aufrufe.append((m, sorted(k)))
        return FakeResp(502)
    monkeypatch.setattr(client._session, "request", fake)
    with pytest.raises(RuntimeError):
        client.upload("Voucher/Factory/uploadTempFile", "a.pdf", b"x")
    assert aufrufe == [("POST", ["files", "timeout"])]


def test_gmi_tags_und_datei(monkeypatch):
    from shared import gmi_client
    c = gmi_client.GmiClient("k", "G-1")
    gesehen = []
    class R(FakeResp):
        content = b"%PDF"
    monkeypatch.setattr(c._session, "request", lambda m, url, **k: gesehen.append((m, url.rsplit("/v3/", 1)[1], k.get("json"))) or R(200, {"success": True}))
    assert c.datei(5) == b"%PDF"
    c.put("documents/5", json={"tags": ["Sevdesk"]})
    assert gesehen == [("GET", "documents/5/file", None), ("PUT", "documents/5", {"tags": ["Sevdesk"]})]


def test_gmi_429_wartet_laenger(monkeypatch):
    from shared import gmi_client
    c = gmi_client.GmiClient("k", "G-1")
    antworten = [FakeResp(429), FakeResp(200, {"maxPages": 1, "records": []})]
    monkeypatch.setattr(c._session, "request", lambda *a, **k: antworten.pop(0))
    pausen = []
    monkeypatch.setattr(gmi_client.time, "sleep", pausen.append)
    c.get("documents")
    assert pausen and pausen[0] >= 10
