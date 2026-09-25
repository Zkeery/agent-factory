"""测试工序：语法检查 + 成品护栏 + 沙箱 smoke import + 启动探测/主路径烟测（确定性，不依赖模型）。"""
from __future__ import annotations

import py_compile
from pathlib import Path

from app.services.codegen_guard import (
    check_embedded_js_safety,
    check_tryon_produces_image,
    check_video_produces_video,
    looks_like_video_idea,
)
from app.services.runner import probe_runnable
from app.services.sandbox import SandboxViolation, check_source, run_smoke_import

DATA_ROOT = Path(__file__).resolve().parents[2] / "data"


def _code_dir(run_id: str) -> Path:
    safe = "".join(c for c in run_id if c.isalnum() or c in "-_")
    d = (DATA_ROOT / "code" / safe).resolve()
    if not d.is_relative_to(DATA_ROOT.resolve()):
        raise ValueError("非法代码目录")
    return d


def has_app_code(run_id: str) -> bool:
    """磁盘上是否已有可重测的 app.py（与 run_tests 路径一致）。"""
    try:
        return (_code_dir(run_id) / "app.py").is_file()
    except ValueError:
        return False


def run_tests(run_id: str, idea: str = "") -> tuple[bool, str]:
    """返回 (是否通过, 说明)。idea 用于视频类运行时护栏。"""
    d = _code_dir(run_id)
    app = d / "app.py"
    req = d / "requirements.txt"
    if not app.is_file():
        return False, "app.py 不存在"
    if not req.is_file():
        return False, "requirements.txt 不存在"
    req_text = req.read_text(encoding="utf-8").lower()
    if "fastapi" not in req_text:
        return False, "requirements.txt 缺少 fastapi"

    source = app.read_text(encoding="utf-8")
    try:
        py_compile.compile(str(app), doraise=True)
    except py_compile.PyCompileError as exc:
        return False, f"语法错误: {exc}"

    ok_js, msg_js = check_embedded_js_safety(source)
    if not ok_js:
        return False, f"成品护栏: {msg_js}"

    ok_tryon, msg_tryon = check_tryon_produces_image(source)
    if not ok_tryon:
        return False, f"成品护栏: {msg_tryon}"

    ok_video, msg_video = check_video_produces_video(source)
    if not ok_video:
        return False, f"成品护栏: {msg_video}"

    try:
        check_source(source, filename=str(app))
    except SandboxViolation as exc:
        return False, f"沙箱拒绝: {exc}"

    ok, msg = run_smoke_import(d)
    if not ok:
        return False, msg

    return probe_runnable(run_id, require_video=looks_like_video_idea(idea))
