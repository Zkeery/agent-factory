"""新生成 PRD 完整性、旧草稿兼容与有限纠错；只用本地 Mock 和 _chat 替身。"""
from __future__ import annotations

import copy
import json
import re

import pytest

from app.core.config import settings
from app.core.errors import AppError
from app.services import deploy, engine, evidence, llm, mock_llm, runner, testing
from app.services.parsing import parse_prd
from app.services.prd_normalize import normalize_prd_fields
from app.services.prd_quality import PrdCompletenessError, generated_prd_issues, validate_generated_prd


@pytest.fixture(autouse=True)
def isolated_prd_runtime(tmp_path, monkeypatch):
    for module in (engine, deploy, evidence, runner, testing):
        monkeypatch.setattr(module, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(settings, "llm_api_key", "")


def decisions_for(result: str) -> list[dict]:
    return [
        {"code": "Q1", "question": "目标用户是谁？", "options": "A 个人用户 / B 团队", "recommendation": "A 个人用户", "answer": "按推荐"},
        {"code": "Q2", "question": "一次使用要得到什么结果？", "options": f"A 说明文档 / B {result}", "recommendation": f"B {result}", "answer": "B"},
        {"code": "Q3", "question": "有什么明确约束？", "options": "A 个人使用 / B 团队协作", "recommendation": "A 个人使用", "answer": "只供个人使用，不增加注册和管理员入口"},
    ]


@pytest.fixture()
def rich_prd():
    return mock_llm.generate_prd("个人待办事项工具", decisions_for("新增事项并完成指定事项"))


def chat_stub(monkeypatch, responses: list[dict]):
    """绕过 SDK 构造，禁止本测试触发网络、初始化凭证或模型调用。"""
    client = object.__new__(llm.RealLLM)
    calls = []
    queue = iter(copy.deepcopy(responses))
    def fake_chat(prompt: str, max_tokens: int = 2000):
        calls.append({"prompt": prompt, "max_tokens": max_tokens})
        return json.dumps(next(queue), ensure_ascii=False)
    monkeypatch.setattr(client, "_chat", fake_chat)
    return client, calls


def replace_section(text: str, heading: str, body: str) -> str:
    pattern = rf"(?ms)^### {re.escape(heading)}\n.*?(?=^### |\Z)"
    replaced, count = re.subn(pattern, f"### {heading}\n\n{body}\n\n", text)
    assert count == 1, f"测试响应缺少要变更的小节：{heading}"
    return replaced


def test_rich_mock_different_businesses_have_specific_fields_features_and_full_answers():
    todo_result = "新增事项并完成指定事项"
    ledger_result = "按有效记录计算收入、支出与余额"
    todo = mock_llm.generate_prd("个人待办事项工具", decisions_for(todo_result))
    ledger = mock_llm.generate_prd("个人记账收支工具", decisions_for(ledger_result))
    assert validate_generated_prd(todo) == todo
    assert validate_generated_prd(ledger) == ledger
    assert "事项名称" in todo["input_process_output"]
    assert "完成状态" in todo["input_process_output"]
    assert "金额" in ledger["input_process_output"]
    assert "收支类型" in ledger["input_process_output"]
    assert todo["main_loop"] != ledger["main_loop"]
    assert "完成指定事项" in todo["main_loop"] and "不新增空白事项" in todo["quality"]
    assert "计算收支" in ledger["main_loop"] and "余额70" in ledger["quality"]
    for prd, result in ((todo, todo_result), (ledger, ledger_result)):
        document = engine.prd_to_markdown(prd)
        assert "A 个人用户" in document
        assert f"B {result}" in document
        assert "只供个人使用，不增加注册和管理员入口" in document
        assert "Mock" in document


def test_legacy_prd_parse_and_markdown_remain_readable_without_new_generation_gate():
    legacy = {
        "goal_users": "个人记账用户，在晚间记录一天的收支。",
        "input_process_output": "输入收入和支出，返回余额。",
        "main_loop": "填写金额后点击保存，再查看列表。",
        "quality": "100元收入减30元支出得到70元余额。",
        "delivery": "先做一页本地演示。",
        "model_cost": "无需运行时模型。",
        "data_nonfunc": "本地存储账目。",
        "launch": "本地运行。",
    }
    parsed = parse_prd(json.dumps(legacy, ensure_ascii=False))
    normalized = normalize_prd_fields(parsed)
    assert normalized == legacy
    document = engine.prd_to_markdown(normalized)
    assert all(value in document for value in legacy.values())
    assert "## 功能、页面与主流程" in document
    # 新门禁只约束新生成，旧快照的读取/呈现不触发该门禁。
    with pytest.raises(PrdCompletenessError):
        validate_generated_prd(normalized)
    assert parse_prd("{}") == {key: "" for key in legacy}


def test_rich_sections_tables_and_feature_ids_survive_parse_normalize_markdown(rich_prd):
    parsed = parse_prd(json.dumps(rich_prd, ensure_ascii=False))
    normalized = normalize_prd_fields(parsed)
    document = engine.prd_to_markdown(normalized)
    assert validate_generated_prd(normalized) == rich_prd
    assert normalized["main_loop"] == parsed["main_loop"] == rich_prd["main_loop"]
    assert normalized["main_loop"] in document and normalized["quality"] in document
    for text in ("### 页面与字段", "### 功能规格", "### 状态与异常", "### 业务验收", "| 用户操作", "系统响应", "可以做", "不可以做"):
        assert text in document
    assert set(re.findall(r"\bF\d{2}\b", document)) == {"F01", "F02", "F03"}
    assert set(re.findall(r"\bAC\d{2}\b", document)) == {"AC01", "AC02", "AC03"}


@pytest.mark.parametrize(("section", "replacement"), [
    ("页面与字段", ""),
    ("状态与异常", ""),
    ("页面与字段", "待定"),
    ("状态与异常", "正常运行"),
])
def test_new_prd_rejects_missing_or_placeholder_page_state_body(rich_prd, section, replacement):
    broken = copy.deepcopy(rich_prd)
    broken["main_loop"] = replace_section(broken["main_loop"], section, replacement)
    with pytest.raises(PrdCompletenessError, match=section):
        validate_generated_prd(broken)


@pytest.mark.parametrize(("mutation", "message"), [
    ("undefined", "未定义功能.*F99"),
    ("uncovered", "未覆盖功能.*F99"),
    ("two_acceptance_cases", "至少需要 AC01"),
    ("no_feature_ids", "稳定功能编号"),
])
def test_new_prd_rejects_broken_feature_acceptance_traceability(rich_prd, mutation, message):
    broken = copy.deepcopy(rich_prd)
    if mutation == "undefined":
        broken["quality"] = broken["quality"].replace("F01", "F99")
    elif mutation == "uncovered":
        broken["main_loop"] += "\n| F99 | 删除指定事项 | P1 | 主操作页 | 点击删除 | 删除所选记录 | 不改变其他事项 |\n"
    elif mutation == "two_acceptance_cases":
        # 保留第三个功能的验收正文，仅移除稳定用例编号，独立检查用例覆盖数。
        broken["quality"] = broken["quality"].replace("AC03", "第三个示例")
    else:
        broken["main_loop"] = re.sub(r"\bF\d{2}\b", "未编号功能", broken["main_loop"])
    with pytest.raises(PrdCompletenessError, match=message):
        validate_generated_prd(broken)


def test_long_background_does_not_substitute_for_development_contract(rich_prd):
    background = "产品围绕用户输入提供价值，需遵守已确认需求。" * 1000
    coarse = {key: background for key in rich_prd if key != "output_type"}
    coarse["output_type"] = "other"
    with pytest.raises(PrdCompletenessError, match="页面与字段"):
        validate_generated_prd(coarse)
    assert generated_prd_issues(rich_prd) == []


@pytest.mark.parametrize("first_response", ["empty_object", "all_pending"])
def test_real_prd_retries_incomplete_valid_json_with_specific_feedback_and_8000_tokens(monkeypatch, rich_prd, first_response):
    coarse = {} if first_response == "empty_object" else {key: "待定" for key in rich_prd if key != "output_type"}
    if first_response == "all_pending":
        coarse["output_type"] = "other"
    client, calls = chat_stub(monkeypatch, [coarse, rich_prd])
    result = client.generate_prd("个人待办事项工具", decisions_for("新增事项并完成指定事项"))
    assert result == rich_prd and len(calls) == 2
    assert [call["max_tokens"] for call in calls] == [8000, 8000]
    retry_prompt = calls[1]["prompt"]
    assert "修正以下缺口" in retry_prompt
    assert "main_loop 缺少具体内容" in retry_prompt
    assert "功能规格需要 F01" in retry_prompt
    assert "业务验收至少需要" in retry_prompt
    assert "B 新增事项并完成指定事项" in calls[0]["prompt"]


@pytest.mark.parametrize("response_kind", ["empty_object", "all_pending", "long_background"])
def test_real_prd_continuously_coarse_json_is_bounded_at_three_attempts(monkeypatch, rich_prd, response_kind):
    if response_kind == "empty_object":
        coarse = {}
    else:
        value = "待定" if response_kind == "all_pending" else "产品应对用户有价值。" * 1000
        coarse = {key: value for key in rich_prd if key != "output_type"}
        coarse["output_type"] = "other"
    client, calls = chat_stub(monkeypatch, [coarse] * 3)
    with pytest.raises(AppError) as error:
        client.generate_prd("个人待办事项工具", decisions_for("新增事项并完成指定事项"))
    assert error.value.code == "prd_content_incomplete"
    assert len(calls) == 3 and all(call["max_tokens"] == 8000 for call in calls)
    assert "修正以下缺口" in calls[1]["prompt"] and "修正以下缺口" in calls[2]["prompt"]


def test_real_prd_parent_context_and_latest_correction_survive_retry(monkeypatch, rich_prd):
    latest_idea = "个人待办事项工具\n最新纠错：保留事项列表，允许撤回完成，不增加登录。"
    source = {
        "parent_run_id": "parent-context-fixture",
        "prd": rich_prd,
        "files": {"app.py": "def export_existing_items(): return 'PARENT_EXPORT_BEHAVIOR'", "requirements.txt": "fastapi\nuvicorn", "README.md": "已有列表与导出能力必须保留"},
        "acceptance_results": [{"id": "scenario-2", "passed": False, "observed": "点击撤回完成后，其他事项也被更改"}],
    }
    client, calls = chat_stub(monkeypatch, [{}, rich_prd])
    assert client.generate_prd(latest_idea, decisions_for("撤回指定事项的完成状态"), source_context=source) == rich_prd
    assert len(calls) == 2
    for call in calls:
        prompt = call["prompt"]
        assert latest_idea in prompt
        assert "PARENT_EXPORT_BEHAVIOR" in prompt
        assert "已有列表与导出能力必须保留" in prompt
        assert "点击撤回完成后，其他事项也被更改" in prompt
        assert "B 撤回指定事项的完成状态" in prompt
        assert '"passed": false' in prompt
        assert "不把父成品当作空白项目" in prompt
def test_mock_supplement_preserves_business_fields_and_scenarios():
    idea = "个人待办清单，添加事项并标记完成\n\n需求补充与纠错\n1. 名称为空或只有空格时禁止新增，其余功能保留。"
    prd = mock_llm.generate_prd(idea, [])
    assert "事项名称" in prd["input_process_output"]
    assert "完成状态" in prd["input_process_output"]
    assert "新增事项" in prd["main_loop"]
    assert "名称为空或只有空格时禁止新增" in prd["input_process_output"]
    assert "周五发送产品周报" in prd["quality"]
