"""实际经过 testing.run_tests 的媒体护栏回归，不运行预览进程。"""
from __future__ import annotations

import pytest

from app.services import testing


TEXT_APP = '''from fastapi import FastAPI
app = FastAPI(title="访谈整理：仅处理粘贴文字，不上传音视频；不生成视频或图片")

@app.post("/generate")
def generate():
    return {"result": "需求：整理访谈。依据：每周花两小时。待确认：付费意愿。"}
'''


@pytest.fixture()
def app_files(monkeypatch, tmp_path):
    monkeypatch.setattr(testing, "DATA_ROOT", tmp_path)
    directory = tmp_path / "code" / "text-app"
    directory.mkdir(parents=True)
    (directory / "app.py").write_text(TEXT_APP, encoding="utf-8")
    (directory / "requirements.txt").write_text("fastapi\nuvicorn\n", encoding="utf-8")
    # 仅替换会创建子进程的两个边界。语法、JS、媒体和 AST 护栏仍运行真实实现。
    monkeypatch.setattr(testing, "run_smoke_import", lambda path: (True, "import替身"))
    probes = []
    def probe(run_id, require_video=False):
        probes.append(require_video)
        return True, "probe替身"
    monkeypatch.setattr(testing, "probe_runnable", probe)
    return directory, probes


def test_text_prd_with_negated_video_words_passes_real_guards(app_files):
    directory, probes = app_files
    ok, reason = testing.run_tests("text-app", idea="不上传音视频，不生成视频或图片", output_type="text")
    assert ok, reason
    assert probes == [False]


def test_video_prd_rejects_text_only_even_without_video_words(app_files):
    directory, probes = app_files
    (directory / "app.py").write_text(TEXT_APP.replace("访谈整理：仅处理粘贴文字，不上传音视频；不生成视频或图片", "新应用"))
    ok, reason = testing.run_tests("text-app", idea="原来只要文本", output_type="video")
    assert not ok and "可播放视频" in reason
    assert probes == []


def test_text_output_still_enforces_ast_safety(app_files):
    directory, probes = app_files
    (directory / "app.py").write_text(TEXT_APP + '\nimport subprocess\n')
    ok, reason = testing.run_tests("text-app", output_type="text")
    assert not ok and "沙箱拒绝" in reason
    assert probes == []


def test_legacy_untyped_prd_keeps_existing_video_guard(app_files):
    directory, probes = app_files
    ok, reason = testing.run_tests("text-app", idea="生成视频")
    assert not ok and "可播放视频" in reason
    assert probes == []
