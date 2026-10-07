"""主路径拒绝请求不能算作可运行验收通过。"""
import io
import urllib.error

import pytest

from app.services import runner


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422, 429, 500])
def test_http_smoke_rejects_unsuccessful_response(monkeypatch, status):
    def reject(*args, **kwargs):
        raise urllib.error.HTTPError(
            "http://127.0.0.1:8100/generate", status, "Rejected", {}, io.BytesIO(b'{"detail":"rejected"}')
        )

    monkeypatch.setattr(runner.urllib.request, "urlopen", reject)
    ok, message, payload = runner.http_main_smoke("http://127.0.0.1:8100")
    assert not ok
    assert "主路径" in message
    assert payload is None


def test_http_smoke_returns_success_payload(monkeypatch):
    class Response(io.BytesIO):
        status = 200

    monkeypatch.setattr(
        runner.urllib.request, "urlopen", lambda *args, **kwargs: Response(b'{"result":"pong"}')
    )
    ok, _, payload = runner.http_main_smoke("http://127.0.0.1:8100")
    assert ok
    assert payload == {"result": "pong"}
