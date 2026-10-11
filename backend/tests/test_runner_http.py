"""主路径拒绝请求不能算作可运行验收通过。"""
import io
import json
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
    if status == 404:
        assert message == "主路径 /generate 不存在"
    elif 400 <= status < 500:
        assert "请求体" in message
        assert "改法" in message
        assert "ping" not in message


def test_http_smoke_sends_scenario_body_not_ping(monkeypatch):
    captured = {}

    class Response(io.BytesIO):
        status = 200

    def opener(req, timeout=0):
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return Response(b'{"result":"ok"}')

    monkeypatch.setattr(runner.urllib.request, "urlopen", opener)
    body = {"input": "选择塔罗抽牌，问今天运势"}
    ok, _, payload = runner.http_main_smoke("http://127.0.0.1:9", body)
    assert ok and payload == {"result": "ok"}
    assert captured["body"] == body
    assert captured["body"] != {"input": "ping"}


def test_http_smoke_returns_success_payload(monkeypatch):
    class Response(io.BytesIO):
        status = 200

    monkeypatch.setattr(
        runner.urllib.request, "urlopen", lambda *args, **kwargs: Response(b'{"result":"pong"}')
    )
    ok, _, payload = runner.http_main_smoke("http://127.0.0.1:8100")
    assert ok
    assert payload == {"result": "pong"}


def test_main_smoke_body_prefers_main_flow_scenario():
    body = runner.main_smoke_body(
        idea="算命",
        prd={"main_loop": "先做星座"},
        scenarios=[{"id": "main-flow", "title": "主流程是否走通", "input": "选择塔罗抽牌，问今天运势", "expected_output": "给出一张牌"}],
    )
    assert body == {"input": "选择塔罗抽牌，问今天运势"}


def test_main_smoke_body_falls_back_without_using_ping():
    from_prd = runner.main_smoke_body(idea="算命", prd={"main_loop": "先完成塔罗抽牌"})
    assert from_prd == {"input": "先完成塔罗抽牌"}
    from_idea = runner.main_smoke_body(idea="帮我做塔罗和星座")
    assert from_idea["input"].startswith("帮我做塔罗")
    default = runner.main_smoke_body()
    assert default == {"input": runner.DEFAULT_SMOKE_INPUT}
    assert "ping" not in json.dumps(default, ensure_ascii=False)
