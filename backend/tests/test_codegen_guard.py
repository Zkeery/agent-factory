"""第十一刀：成品嵌入 JS 护栏 + mock 生成物可 compile/护栏通过。"""
from __future__ import annotations

import py_compile
from pathlib import Path

from app.services.codegen_guard import check_embedded_js_safety, check_video_produces_video
from app.services.mock_llm import generate_code


def test_codegen_guard_rejects_broken_js_newline():
    """普通三引号里 <script> 字符串跨真换行 → 护栏失败。"""
    nl = chr(10)
    broken = (
        "from fastapi import FastAPI" + nl
        + "app = FastAPI()" + nl
        + "PAGE = " + chr(34) * 3 + nl
        + "<html><body><script>" + nl
        + "function f() {" + nl
        + '  var msg = "hello' + nl
        + 'world";' + nl
        + "  console.log(msg);" + nl
        + "}" + nl
        + "</script></body></html>" + nl
        + chr(34) * 3 + nl
    )
    ok, msg = check_embedded_js_safety(broken)
    assert ok is False
    assert ("换行" in msg) or ("嵌入" in msg)


def test_codegen_guard_accepts_raw_or_safe():
    """raw 三引号，或普通三引号内 JS 字面 \\n（源码两字符）应通过。"""
    nl = chr(10)
    js_nl = chr(92) + "n"  # 写入成品源码的两个字符：\ 与 n
    raw_ok = (
        "PAGE = r" + chr(34) * 3 + nl
        + "<html><body><script>" + nl
        + "function f() {" + nl
        + '  var msg = "hello' + js_nl + 'world";' + nl
        + "  console.log(msg);" + nl
        + "}" + nl
        + "</script></body></html>" + nl
        + chr(34) * 3 + nl
    )
    ok, msg = check_embedded_js_safety(raw_ok)
    assert ok is True, msg

    safe_escaped = (
        "PAGE = " + chr(34) * 3 + nl
        + "<html><body><script>" + nl
        + 'var msg = "hello' + js_nl + 'world";' + nl
        + "</script></body></html>" + nl
        + chr(34) * 3 + nl
    )
    ok2, msg2 = check_embedded_js_safety(safe_escaped)
    assert ok2 is True, msg2


def test_mock_code_passes_guard_and_compile(tmp_path: Path):
    blocks = generate_code("护栏演示想法", {"goal_users": "测试"})
    app_src = blocks["app"]
    ok, msg = check_embedded_js_safety(app_src)
    assert ok is True, msg
    target = tmp_path / "app.py"
    target.write_text(app_src, encoding="utf-8")
    py_compile.compile(str(target), doraise=True)
    assert "HOME_HTML = r" + chr(34) * 3 in app_src
    assert "@app.get" in app_src
    assert "/generate" in app_src
    assert "本地回落" in app_src
    assert "HTTPException" not in app_src
    assert "status_code=500" not in app_src
    assert "status_code = 500" not in app_src


def test_mock_generate_no_key_returns_200_semantics():
    """静态断言：mock 成品无 Key 分支返回 dict result，不 raise 5xx。"""
    app_src = generate_code("无Key语义", {})["app"]
    assert "if not key:" in app_src
    assert "return local" in app_src
    assert "result" in app_src


def test_run_tests_rejects_broken_embedded_js(monkeypatch, tmp_path: Path):
    """接线：py_compile 后护栏失败应返回「成品护栏」。"""
    from app.services import testing, runner

    root = tmp_path / "data"
    (root / "code").mkdir(parents=True)
    monkeypatch.setattr(testing, "DATA_ROOT", root)
    monkeypatch.setattr(runner, "DATA_ROOT", root)

    nl = chr(10)
    broken = (
        "from fastapi import FastAPI" + nl
        + "app = FastAPI()" + nl
        + "PAGE = " + chr(34) * 3 + nl
        + "<html><body><script>" + nl
        + 'var msg = "hello' + nl
        + 'world";' + nl
        + "</script></body></html>" + nl
        + chr(34) * 3 + nl
        + nl
        + '@app.post("/generate")' + nl
        + "def generate():" + nl
        + '    return {"result": "ok"}' + nl
    )
    d = root / "code" / "run-js-bad"
    d.mkdir(parents=True)
    (d / "app.py").write_text(broken, encoding="utf-8")
    (d / "requirements.txt").write_text("fastapi" + chr(10) + "uvicorn" + chr(10), encoding="utf-8")
    ok, msg = testing.run_tests("run-js-bad")
    assert ok is False
    assert "成品护栏" in msg


def test_video_guard_rejects_text_fallback():
    src = (
        "from fastapi import FastAPI\n"
        "app = FastAPI()\n"
        "TITLE = '短视频生成器'\n"
        "@app.post('/generate')\n"
        "def generate():\n"
        "    try:\n"
        "        return {'result': 'ok', 'video_url': '/video.mp4'}\n"
        "    except Exception as exc:\n"
        "        return {'result': '本地视频合成异常：' + str(exc)}\n"
    )
    ok, msg = check_video_produces_video(src)
    assert ok is False
    assert "纯文案" in msg


def test_video_guard_accepts_video_exit():
    src = (
        "from fastapi import FastAPI\n"
        "app = FastAPI()\n"
        "TITLE = '短视频生成器'\n"
        "@app.post('/generate')\n"
        "def generate():\n"
        "    return {'result': 'ok', 'video_url': '/video.avi'}\n"
    )
    ok, msg = check_video_produces_video(src)
    assert ok is True


def test_video_guard_skips_non_video():
    src = "from fastapi import FastAPI\napp = FastAPI()\n"
    ok, msg = check_video_produces_video(src)
    assert ok is True
