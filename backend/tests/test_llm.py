"""第 2 阶段测试：LLM 工厂与解析器结构校验。"""
from __future__ import annotations

import pytest

from app.core.config import settings
from app.core.errors import AppError
from app.services import llm, parsing


def test_get_llm_mock(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "mock")
    assert isinstance(llm.get_llm(), llm.MockLLM)


def test_get_llm_deepseek_no_key_raises(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "deepseek")
    monkeypatch.setattr(settings, "llm_api_key", "")
    with pytest.raises(AppError) as exc:
        llm.get_llm()
    assert exc.value.code == "llm_key_missing"


def test_unknown_provider_raises(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "nope")
    with pytest.raises(AppError):
        llm.get_llm()


def test_parse_clarify_valid():
    raw = '[{"code":"Q1","question":"谁用","options":"A/B","recommendation":"A","consequence":"x"}]'
    cards = parsing.parse_clarify(raw)
    assert len(cards) == 1
    assert cards[0]["code"] == "Q1"


def test_parse_clarify_with_fence():
    raw = '```json\n[{"code":"Q1","question":"q","options":"A/B"}]\n```'
    cards = parsing.parse_clarify(raw)
    assert len(cards) == 1


def test_parse_clarify_more_than_5_is_flaw_not_error():
    raw = "[" + ",".join(
        '{"code":"Q%d","question":"q","options":"A/B"}' % i for i in range(1, 7)
    ) + "]"
    cards = parsing.parse_clarify(raw)
    assert len(cards) == 6  # 记为瑕疵，不作为解析失败


def test_parse_clarify_invalid_raises():
    with pytest.raises(ValueError):
        parsing.parse_clarify("不是 JSON")


def test_parse_clarify_wrapped_object():
    raw = '{"cards":[{"code":"Q1","question":"q","options":"A/B"}]}'
    cards = parsing.parse_clarify(raw)
    assert len(cards) == 1


def test_parse_prd_valid():
    raw = '{"goal_users":"u","input_process_output":"i","main_loop":"m","quality":"q","delivery":"d","model_cost":"c","data_nonfunc":"n","launch":"l"}'
    prd = parsing.parse_prd(raw)
    assert prd["goal_users"] == "u"


def test_parse_prd_missing_fields_defaults():
    raw = '{"goal_users":"u"}'
    prd = parsing.parse_prd(raw)
    assert prd["launch"] == ""


def test_strip_fence():
    assert parsing.strip_fence("```python\nprint(1)\n```") == "print(1)"
    assert parsing.strip_fence("plain text") == "plain text"


def test_parse_code_strips_markdown_fence():
    """模型在块内再套一层 ```python 围栏时，解析后代码不带围栏。"""
    raw = (
        "===APP===\n"
        "```python\n"
        "from fastapi import FastAPI\n"
        "app = FastAPI()\n"
        "```\n"
        "===REQUIREMENTS===\n"
        "fastapi\n"
        "uvicorn\n"
        "===README===\n"
        "# 说明\n"
        "启动方式\n"
    )
    blocks = parsing.parse_code(raw)
    assert blocks["app"] == "from fastapi import FastAPI\napp = FastAPI()"
    assert blocks["requirements"] == "fastapi\nuvicorn"
    assert "```" not in blocks["app"]


def test_parse_code_no_fence_untouched():
    raw = (
        "===APP===\n"
        "print('hi')\n"
        "===REQUIREMENTS===\n"
        "fastapi\n"
        "===README===\n"
        "readme\n"
    )
    blocks = parsing.parse_code(raw)
    assert blocks["app"] == "print('hi')"


def test_parse_code_strips_note_lines():
    raw = (
        "===APP===\n"
        "from fastapi import FastAPI\n"
        "app = FastAPI()\n"
        "（见上）\n"
        "return_hint = \"错误：无法计算\"\n"
        "===REQUIREMENTS===\nfastapi\n"
        "===README===\n说明\n"
    )
    blocks = parsing.parse_code(raw)
    assert "（见上）" not in blocks["app"]
    assert "return_hint" in blocks["app"]  # 合法行保留


def test_parse_code_keeps_chinese_string_line():
    raw = (
        "===APP===\n"
        'msg = "错误：除数不能为零"\n'
        "===REQUIREMENTS===\nfastapi\n"
        "===README===\n说明\n"
    )
    blocks = parsing.parse_code(raw)
    assert "错误：除数不能为零" in blocks["app"]
