"""prefer_open_url：纯 API 成品应落到 /docs，而不是 404 根路径。"""
from __future__ import annotations

from app.services import runner


class _Resp:
    def __init__(self, status: int, ctype: str, body: bytes = b""):
        self.status = status
        self.headers = {"content-type": ctype}
        self._body = body

    def read(self, n: int = -1):
        return self._body if n < 0 else self._body[:n]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_prefer_open_url_uses_docs_when_root_is_json_404(monkeypatch):
    calls: list[str] = []

    def fake_urlopen(req, timeout=1.5):  # noqa: ARG001
        url = req.full_url if hasattr(req, "full_url") else str(req)
        calls.append(url)
        if url.rstrip("/").endswith(":9999"):
            # root
            raise runner.urllib.error.HTTPError(url, 404, "Not Found", hdrs=None, fp=None)
        if url.endswith("/docs"):
            return _Resp(200, "text/html; charset=utf-8", b"<!DOCTYPE html>")
        raise AssertionError(url)

    monkeypatch.setattr(runner.urllib.request, "urlopen", fake_urlopen)
    # HTTPError path: urlopen raises for 404 in stdlib — simulate root raise then docs ok
    def fake_urlopen2(req, timeout=1.5):  # noqa: ARG001
        url = req.full_url if hasattr(req, "full_url") else getattr(req, "selector", None) or req.get_full_url()
        calls.append(url)
        if url.endswith("/") or url.endswith(":9999"):
            raise runner.urllib.error.HTTPError(url, 404, "Not Found", hdrs=type("H", (), {"get": lambda *a, **k: ""})(), fp=None)
        if url.endswith("/docs"):
            return _Resp(200, "text/html; charset=utf-8", b"<!DOCTYPE html>")
        raise runner.urllib.error.URLError("skip")

    calls.clear()
    monkeypatch.setattr(runner.urllib.request, "urlopen", fake_urlopen2)
    out = runner.prefer_open_url("http://127.0.0.1:9999")
    assert out == "http://127.0.0.1:9999/docs"


def test_prefer_open_url_keeps_html_home(monkeypatch):
    def fake_urlopen(req, timeout=1.5):  # noqa: ARG001
        return _Resp(200, "text/html; charset=utf-8", b"<!DOCTYPE html><title>hi</title>")

    monkeypatch.setattr(runner.urllib.request, "urlopen", fake_urlopen)
    out = runner.prefer_open_url("http://127.0.0.1:9999")
    assert out == "http://127.0.0.1:9999"
