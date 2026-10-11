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


def main_flow_scenario(scenarios: list[dict]) -> dict | None:
    """用户只验收主流程。新数据用 main-flow；历史多场景取主流程标题，否则取第一条。"""
    usable = [item for item in scenarios if isinstance(item, dict) and item.get("id")]
    for item in usable:
        if item.get("id") == "main-flow":
            return item
    for item in usable:
        title = str(item.get("title") or "")
        if any(word in title for word in ("主流程", "主链路", "主路径")):
            return item
    return usable[0] if usable else None


def validate_scenario_results(scenarios: list[dict], results: list) -> None:
    validate_scenarios(scenarios)
    main = main_flow_scenario(scenarios)
    if main is None:
        raise ValueError("请先写清主流程怎么操作、怎样算走通")
    known = {item["id"] for item in scenarios}
    seen: set[str] = set()
    by_id = {}
    for item in results:
        scenario_id = item.scenario_id
        if scenario_id in seen:
            raise ValueError("验收记录重复")
        seen.add(scenario_id)
        if scenario_id not in known:
            raise ValueError("验收记录包含不属于本版本的场景")
        if not str(item.observation or "").strip():
            raise ValueError("已提交的验收记录需要填写实际结果")
        by_id[scenario_id] = item
    main_result = by_id.get(main["id"])
    if main_result is None or not main_result.passed:
        raise ValueError("主流程未通过，请先写下问题并创建修改版")


MAIN_FLOW_CHECK_ID = "main_flow"


def _dicts(raw) -> list[dict]:
    return [item for item in json_list(raw) if isinstance(item, dict)]


def main_flow_rejected(run) -> bool:
    """主流程已被记为没走通，且这一版还没有交付。

    只认主流程自己的结论。旁路场景失败、或主流程已走通后的其他反馈，都不算整版未通过。
    没有场景定义时，任一 passed 为 false 的观察，或基础验收写下的主流程未通过标记，视为未通过。
    """
    if getattr(run, "current_stage", None) == "delivered" or getattr(run, "accepted_at", None):
        return False
    scenarios = _dicts(getattr(run, "acceptance_scenarios", None))
    results = _dicts(getattr(run, "acceptance_results", None))
    main = main_flow_scenario(scenarios)
    if main is not None:
        for item in results:
            if item.get("scenario_id") == main.get("id"):
                return item.get("passed") is False
        return False
    if any(item.get("passed") is False for item in results):
        return True
    return any(
        item.get("id") == MAIN_FLOW_CHECK_ID and item.get("passed") is False
        for item in _dicts(getattr(run, "acceptance_checklist", None))
    )


def acceptance_outcome(run) -> str | None:
    """给界面用的验收结论。不改变 current_stage。

    accepted：已经交付，或已经记下验收时间。
    rejected：待验收且主流程没走通。
    pending：待验收，主流程还没被判为没走通。
    None：还没到人工验收。
    """
    if getattr(run, "accepted_at", None) or getattr(run, "current_stage", None) == "delivered":
        return "accepted"
    if getattr(run, "current_stage", None) != "awaiting_acceptance":
        return None
    return "rejected" if main_flow_rejected(run) else "pending"


def apply_main_flow_feedback(run, main_passed: bool | None) -> None:
    """基础验收没有场景结果时，记住用户明确说主流程没走通。

    场景模式以验收记录为准，不在这里覆盖观察。主流程改为走通时，去掉先前的未通过标记。
    """
    if main_passed is None:
        return
    checklist = [item for item in _dicts(run.acceptance_checklist) if item.get("id") != MAIN_FLOW_CHECK_ID]
    scenarios = _dicts(run.acceptance_scenarios)
    main = main_flow_scenario(scenarios)
    recorded = False
    if main is not None:
        recorded = any(
            item.get("scenario_id") == main.get("id") and isinstance(item.get("passed"), bool)
            for item in _dicts(run.acceptance_results)
        )
    if main_passed is False and not recorded:
        checklist.append({"id": MAIN_FLOW_CHECK_ID, "label": "主流程", "passed": False})
    run.acceptance_checklist = dump(checklist)


def parents_with_revisions(session, parent_ids) -> set[str]:
    """已经有子版本的运行。隐藏的失败重跑不取消「修改版曾经创建」这一事实。"""
    from app.models import FactoryRun

    ids = {item for item in parent_ids if item}
    if not ids:
        return set()
    rows = session.query(FactoryRun.parent_run_id).filter(FactoryRun.parent_run_id.in_(ids)).distinct().all()
    return {row[0] for row in rows if row[0]}
