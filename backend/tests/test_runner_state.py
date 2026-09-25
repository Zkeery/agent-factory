"""预览运行态落盘辅助函数测试（不拉起真实子进程）。"""
from __future__ import annotations

import os

from app.services import runner


def test_state_write_read_remove(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "PREVIEW_DIR", tmp_path / "preview")
    rid = "run-123"
    assert runner._read_state(rid) is None

    runner._write_state(rid, pid=4242, port=8001)
    assert runner._read_state(rid) == {"pid": 4242, "port": 8001}

    runner._remove_state(rid)
    assert runner._read_state(rid) is None


def test_read_state_ignores_corrupt_file(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "PREVIEW_DIR", tmp_path / "preview")
    rid = "bad"
    runner._write_state(rid, pid=1, port=1)
    runner._state_path(rid).write_text("{not json", encoding="utf-8")
    assert runner._read_state(rid) is None


def test_pid_alive():
    assert runner._pid_alive(os.getpid()) is True
    assert runner._pid_alive(0) is False
    assert runner._pid_alive(-1) is False
    assert runner._pid_alive(99999999) is False
