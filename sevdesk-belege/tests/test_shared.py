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
