"""保留澄清决策的具体含义；解析有依据的简写，不修改历史记录。"""
from __future__ import annotations

import re
from collections.abc import Mapping


def _option_for_label(label: str, options: str) -> str | None:
    choices = dict.fromkeys(item.strip() for item in options.split("/") if item.strip())
    matches = []
    for option in choices:
        match = re.match(r"^([ABC])(?:[\s.、:：)）．-]+|(?=[\u4e00-\u9fff]))", option, re.IGNORECASE)
        if match and match.group(1).upper() == label and option[match.end():].strip():
            matches.append(option)
    return matches[0] if len(matches) == 1 else None


def _resolve_answer(answer: str | None, *, options: str, recommendation: str) -> tuple[str | None, str | None]:
    if answer is None:
        return None, None
    selected = answer.strip()
    if selected == "按推荐":
        concrete = recommendation.strip()
        if not concrete or concrete == "按推荐":
            return answer, "用户选择按推荐，但该决策未提供具体推荐答案，需要补充确认。"
        resolved, gap = _resolve_answer(concrete, options=options, recommendation="")
        return resolved, gap
    if selected.upper() in {"A", "B", "C"}:
        option = _option_for_label(selected.upper(), options)
        if option is not None:
            return option, None
        return answer, f"用户选择 {selected}，现有选项未提供唯一对应的完整答案，需要补充确认。"
    return answer, None


def normalize_decision_answer(answer: str | None, *, options: str = "", recommendation: str = "") -> str | None:
    """只展开字面量“按推荐”和可唯一匹配的 A/B/C；自定义回答原样保留。"""
    return _resolve_answer(answer, options=options or "", recommendation=recommendation or "")[0]


def decision_model_context(decision: object) -> dict[str, object]:
    """接受映射、数据库 Decision 或输入schema，保留原回答和解析所需上下文。"""
    def field(name: str, default: object = "") -> object:
        return decision.get(name, default) if isinstance(decision, Mapping) else getattr(decision, name, default)

    options = field("options") or ""
    recommendation = field("recommendation") or ""
    answer = field("answer", None)
    resolved, gap = _resolve_answer(answer, options=options, recommendation=recommendation)
    payload = {
        "code": field("code"), "question": field("question"),
        "options": options, "recommendation": recommendation,
        "answer": resolved, "raw_answer": field("raw_answer", answer),
    }
    if gap:
        payload["answer_gap"] = gap
    return payload
