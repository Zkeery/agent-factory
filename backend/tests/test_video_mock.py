"""第十二刀：视频类 idea mock 产出可播模板。"""
from __future__ import annotations

import py_compile
from pathlib import Path

from app.services.codegen_guard import check_embedded_js_safety
from app.services.mock_llm import generate_code, _is_video_idea


def test_is_video_idea():
    assert _is_video_idea("做一个生成短视频的小工具") is True
    assert _is_video_idea("video clip maker") is True
    assert _is_video_idea("成片导出助手") is True
    assert _is_video_idea("记账本") is False


def test_video_mock_contains_video_tag_and_mp4(tmp_path: Path):
    blocks = generate_code("做一个生成视频的小工具", {"goal_users": "个人"})
    app_src = blocks["app"]
    assert "<video" in app_src
    assert "video/mp4" in app_src
    assert "本地演示片" in app_src
    assert "提示词生成器" not in app_src or "<video" in app_src
    ok, msg = check_embedded_js_safety(app_src)
    assert ok is True, msg
    target = tmp_path / "app.py"
    target.write_text(app_src, encoding="utf-8")
    py_compile.compile(str(target), doraise=True)


def test_normal_idea_keeps_text_demo():
    app_src = generate_code("做一个记账助手", {})["app"]
    assert "<video" not in app_src
    assert "本地回落" in app_src
