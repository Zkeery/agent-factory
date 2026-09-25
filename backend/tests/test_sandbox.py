"""生成代码沙箱：静态检查与 smoke import。"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.services import testing
from app.services.sandbox import (
    SandboxViolation,
    check_source,
    format_sandbox_import_error,
    run_smoke_import_process,
)

SAFE_APP = """# safe
import os
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class Req(BaseModel):
    input: str

@app.post("/generate")
def generate(req: Req):
    key = os.getenv("DEEPSEEK_API_KEY")
    if not key:
        return {"error": "missing"}
    return {"result": req.input}
"""

SAFE_REQ = "fastapi\nuvicorn\n"


def _write_run(tmp_code_root: Path, run_id: str, app: str, req: str = SAFE_REQ) -> None:
    d = tmp_code_root / run_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "app.py").write_text(app, encoding="utf-8")
    (d / "requirements.txt").write_text(req, encoding="utf-8")


@pytest.fixture()
def code_root(monkeypatch, tmp_path: Path):
    from app.services import runner

    root = tmp_path / "data"
    (root / "code").mkdir(parents=True)
    monkeypatch.setattr(testing, "DATA_ROOT", root)
    monkeypatch.setattr(runner, "DATA_ROOT", root)
    return root / "code"


def test_check_source_allows_mock_style():
    check_source(SAFE_APP)


@pytest.mark.parametrize(
    "bad",
    [
        "import subprocess\n",
        "import socket\n",
        "from os import system\n",
        "import os\nos.system('ls')\n",
        "eval('1')\n",
        "exec('x=1')\n",
        "import pathlib\n",
    ],
)
def test_check_source_blocks_danger(bad: str):
    with pytest.raises(SandboxViolation):
        check_source(bad)


def test_run_tests_passes_safe(code_root: Path):
    _write_run(code_root, "run-safe", SAFE_APP)
    ok, msg = testing.run_tests("run-safe")
    assert ok, msg


def test_run_tests_rejects_subprocess(code_root: Path):
    bad = SAFE_APP.replace("import os\n", "import os\nimport subprocess\n")
    _write_run(code_root, "run-bad", bad)
    ok, msg = testing.run_tests("run-bad")
    assert not ok
    assert "沙箱拒绝" in msg


def test_run_tests_rejects_missing_fastapi(code_root: Path):
    _write_run(code_root, "run-noreq", SAFE_APP, req="flask\n")
    ok, msg = testing.run_tests("run-noreq")
    assert not ok
    assert "fastapi" in msg.lower()


def test_run_tests_probe_requires_generate_route(code_root: Path):
    """能 import 但没有 /generate 时，启动探测后的主路径烟测应失败。"""
    app = """from fastapi import FastAPI
app = FastAPI()

@app.get("/")
def root():
    return {"ok": True}
"""
    _write_run(code_root, "run-nogen", app)
    ok, msg = testing.run_tests("run-nogen")
    assert not ok
    assert "generate" in msg.lower() or "主路径" in msg


def test_probe_runnable_direct(code_root: Path):
    from app.services import runner

    _write_run(code_root, "run-probe", SAFE_APP)
    ok, msg = runner.probe_runnable("run-probe")
    assert ok, msg


SAFE_APP_WITH_PIL = """# safe with pillow
import os
from fastapi import FastAPI
from pydantic import BaseModel
from PIL import Image

app = FastAPI()

class Req(BaseModel):
    input: str

@app.post("/generate")
def generate(req: Req):
    _ = Image.new("RGB", (8, 8), color=(255, 0, 0))
    key = os.getenv("DEEPSEEK_API_KEY")
    if not key:
        return {"error": "missing"}
    return {"result": req.input}
"""

SAFE_REQ_WITH_PIL = "fastapi\nuvicorn\npillow\n"


def test_format_sandbox_import_error_prefers_module_not_found():
    """长 traceback 截取首 300 字会停在 ImageDr；应抽出末尾 ModuleNotFoundError。"""
    traceback = (
        "Traceback (most recent call last):\n"
        '  File "<string>", line 1, in <module>\n'
        "  File \"./app.py\", line 15, in <module>\n"
        "    from PIL import Image, ImageDraw, ImageFilter\n"
        + ("  ... filler line that pads the head so [:300] cuts mid-import ...\n" * 8)
        + "ModuleNotFoundError: No module named 'PIL'\n"
    )
    # 证明旧行为会截到 ImageDr
    assert "ImageDr" in traceback[:300]
    assert "No module named 'PIL'" not in traceback[:300]

    msg = format_sandbox_import_error(traceback)
    assert msg.startswith("沙箱导入失败:")
    assert "No module named 'PIL'" in msg
    assert "ImageDr" not in msg


def test_format_sandbox_import_error_falls_back_to_tail():
    long_err = ("x" * 50 + "\n") * 20 + "FINAL_TAIL_MARKER_UNIQUE"
    msg = format_sandbox_import_error(long_err, max_len=80)
    assert msg.startswith("沙箱导入失败:")
    assert "FINAL_TAIL_MARKER_UNIQUE" in msg
    assert len(msg) <= len("沙箱导入失败: ") + 80


def test_run_smoke_import_process_allows_pillow(tmp_path: Path):
    """进程沙箱应对含 PIL 的安全 app 通过（依赖 backend venv 已装 pillow）。"""
    d = tmp_path / "pil-code"
    d.mkdir()
    (d / "app.py").write_text(SAFE_APP_WITH_PIL, encoding="utf-8")
    (d / "requirements.txt").write_text(SAFE_REQ_WITH_PIL, encoding="utf-8")
    ok, msg = run_smoke_import_process(d)
    assert ok, msg


def test_run_tests_passes_safe_with_pillow(code_root: Path):
    _write_run(code_root, "run-pil", SAFE_APP_WITH_PIL, req=SAFE_REQ_WITH_PIL)
    ok, msg = testing.run_tests("run-pil")
    assert ok, msg
