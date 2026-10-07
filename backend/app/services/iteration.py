"""需求修订、父版本上下文和业务场景的共享结构，不执行生成代码。"""
from __future__ import annotations

import json

from app.schemas import AcceptanceScenariosRequest


def json_list(raw: str | None) -> list:
    try:
        value = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    return value if isinstance(value, list) else []


def json_dict(raw: str | None) -> dict:
    try:
        value = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def dump(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def effective_idea(run) -> str:
    """最新用户纠错优先于初始描述和旧决策；所有历史仍留在 Run 中。"""
    sections = [run.idea]
    parent = json_dict(run.parent_context)
    if parent.get("prd"):
        sections.append(
            "父版本已经确认的有效需求（前面的初始想法仅作历史背景；未要求修改的部分继续保留）：\n"
            + dump(parent["prd"])
        )
    if run.change_request:
        sections.append("本次基于父版本的修改要求：\n" + run.change_request)
    feedback = json_list(run.requirement_feedback)
    if feedback:
        sections.append(
            "需求补充与纠错（按时间顺序，后条优先；与旧决策冲突时以这里的最新明确要求为准）：\n"
            + "\n".join(f"{i + 1}. {item['feedback']}" for i, item in enumerate(feedback))
        )
    return "\n\n".join(sections)


def validate_scenarios(items: list[dict]) -> list[dict]:
    validated = AcceptanceScenariosRequest(scenarios=items)
    return [item.model_dump() for item in validated.scenarios]


def validate_scenario_results(scenarios: list[dict], results: list) -> None:
    validate_scenarios(scenarios)
    expected = {item["id"] for item in scenarios}
    actual = [item.scenario_id for item in results]
    if len(actual) != len(set(actual)) or set(actual) != expected:
        raise ValueError("请逐项填写本版本的全部验收场景，不得缺失、重复或包含旧场景")
    if any(not item.passed or not item.observation.strip() for item in results):
        raise ValueError("每条业务场景必须通过，并填写实际观察结果后才能交付")
