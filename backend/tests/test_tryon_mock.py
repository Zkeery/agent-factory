"""第十四刀：试衣类 idea mock 产出可查看预览图；护栏拒绝纯文案。"""
from __future__ import annotations

import py_compile
from pathlib import Path

from app.services.codegen_guard import check_embedded_js_safety, check_tryon_produces_image
from app.services.mock_llm import generate_code, _is_tryon_idea


def test_is_tryon_idea():
    assert _is_tryon_idea("做一个线上试衣间") is True
    assert _is_tryon_idea("虚拟试穿预览") is True
    assert _is_tryon_idea("换装看看上身效果") is True
    assert _is_tryon_idea("virtual try-on tool") is True
    assert _is_tryon_idea("上传照片看上身效果") is True
    assert _is_tryon_idea("记账本") is False
    assert _is_tryon_idea("生成短视频") is False


def test_tryon_mock_contains_image_markers(tmp_path: Path):
    blocks = generate_code("做一个虚拟试穿小工具", {"goal_users": "个人"})
    app_src = blocks["app"]
    assert "image_base64" in app_src
    assert "image/png" in app_src or "/preview.png" in app_src
    assert "<img" in app_src
    assert "本地演示图" in app_src
    assert "试穿预览" in app_src
    assert "pillow" in blocks["requirements"].lower()
    assert "python-multipart" in blocks["requirements"]
    ok, msg = check_embedded_js_safety(app_src)
    assert ok is True, msg
    ok2, msg2 = check_tryon_produces_image(app_src)
    assert ok2 is True, msg2
    target = tmp_path / "app.py"
    target.write_text(app_src, encoding="utf-8")
    py_compile.compile(str(target), doraise=True)


def test_tryon_guard_rejects_text_only_outfit_plan():
    """有试衣关键词 + 换装文案回落 + 无强出图标记 → 护栏失败。"""
    nl = chr(10)
    q3 = chr(34) * 3
    bad = nl.join(
        [
            "from fastapi import FastAPI",
            "from fastapi.responses import HTMLResponse, JSONResponse",
            "from pydantic import BaseModel",
            "",
            'app = FastAPI(title="AI 试衣间")',
            "",
            "def local_fallback(user_text: str) -> str:",
            '    return "【本地演示模式】规则化换装预览说明：换装建议保持姿态不变……"',
            "",
            "HOME = r" + q3 + "<!DOCTYPE html><html><body>",
            "<h1>试衣间</h1>",
            '<input type="file" id="photo"/>',
            '<div id="preview"></div>',
            "<button>生成试穿预览</button>",
            "<script>",
            'document.getElementById("photo").onchange = function(e){',
            "  var url = URL.createObjectURL(e.target.files[0]);",
            '  document.getElementById("preview").innerHTML = "<img src=\"" + url + "\"/>";',
            "};",
            "</script>",
            "</body></html>" + q3,
            "",
            "class Req(BaseModel):",
            '    input: str = ""',
            "",
            '@app.get("/", response_class=HTMLResponse)',
            "def home():",
            "    return HOME",
            "",
            '@app.post("/generate")',
            "def generate(req: Req):",
            '    return JSONResponse({"result": local_fallback(req.input)})',
            "",
        ]
    )
    ok, msg = check_tryon_produces_image(bad)
    assert ok is False
    assert ("预览图" in msg) or ("试衣" in msg)


def test_tryon_guard_accepts_pillow_template():
    app_src = generate_code("试穿换装预览", {})["app"]
    ok, msg = check_tryon_produces_image(app_src)
    assert ok is True, msg


def test_normal_idea_unaffected_by_tryon_guard():
    app_src = generate_code("做一个记账助手", {})["app"]
    ok, msg = check_tryon_produces_image(app_src)
    assert ok is True, msg
    assert "image_base64" not in app_src
