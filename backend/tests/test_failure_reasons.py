"""失败原因分类与人话映射测试（第十六刀）。"""
from __future__ import annotations

from app.services import failure_reasons


def test_classify_sandbox():
    assert failure_reasons.classify_test_reason("沙箱拒绝: 禁止调用: eval") == "sandbox_blocked"


def test_classify_syntax():
    assert failure_reasons.classify_test_reason("语法错误: invalid syntax") == "code_syntax"


def test_classify_guard():
    assert failure_reasons.classify_test_reason("成品护栏: 缺图片") == "code_guard"


def test_classify_deps():
    assert failure_reasons.classify_test_reason("requirements.txt 缺少 fastapi") == "code_deps"


def test_classify_runtime():
    assert failure_reasons.classify_test_reason("主路径 /generate 不存在") == "code_runtime"


def test_pm_text_known():
    msg, act = failure_reasons.pm_text("sandbox_blocked")
    assert "安全" in msg
    assert act


def test_pm_text_fallback():
    assert failure_reasons.pm_text("")[0] == "这次没做成功"
    assert failure_reasons.pm_text("totally_unknown")[0] == "这次没做成功"
