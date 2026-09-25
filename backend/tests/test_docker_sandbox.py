"""Docker 沙箱选择逻辑（无 Docker 时测回退，不要求本机有守护进程）。"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.services import sandbox
from app.services import docker_sandbox


SAFE_APP = """# safe
import os
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class Req(BaseModel):
    input: str

@app.post("/generate")
def generate(req: Req):
    return {"result": req.input, "k": os.getenv("X")}
"""


@pytest.fixture()
def code_dir(tmp_path: Path) -> Path:
    d = tmp_path / "code"
    d.mkdir()
    (d / "app.py").write_text(SAFE_APP, encoding="utf-8")
    (d / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    return d


def test_auto_falls_back_to_process_without_docker(code_dir: Path, monkeypatch):
    monkeypatch.setattr(sandbox.settings, "sandbox_mode", "auto")
    monkeypatch.setattr(docker_sandbox, "docker_sandbox_ready", lambda: False)
    ok, msg = sandbox.run_smoke_import(code_dir)
    assert ok, msg
    assert "沙箱" in msg


def test_docker_mode_errors_when_unavailable(code_dir: Path, monkeypatch):
    monkeypatch.setattr(sandbox.settings, "sandbox_mode", "docker")
    monkeypatch.setattr(docker_sandbox, "docker_sandbox_ready", lambda: False)
    ok, msg = sandbox.run_smoke_import(code_dir)
    assert not ok
    assert "Docker" in msg or "docker" in msg


def test_docker_mode_uses_docker_when_ready(code_dir: Path, monkeypatch):
    monkeypatch.setattr(sandbox.settings, "sandbox_mode", "docker")
    monkeypatch.setattr(docker_sandbox, "docker_sandbox_ready", lambda: True)

    def fake_docker(path: Path):
        assert path == code_dir
        return True, "Docker 沙箱语法与导入检查通过"

    monkeypatch.setattr(docker_sandbox, "run_smoke_import_docker", fake_docker)
    # dispatcher imports inside function — patch module attr used after import
    import app.services.docker_sandbox as ds

    monkeypatch.setattr(ds, "run_smoke_import_docker", fake_docker)
    ok, msg = sandbox.run_smoke_import(code_dir)
    assert ok
    assert "Docker" in msg
