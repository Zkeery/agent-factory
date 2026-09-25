"""PRD 字段规范化：去掉标题复读与空转「待定」。"""
from __future__ import annotations

# 与 engine.prd_to_markdown 中文标题一致
PRD_FIELD_TITLES: dict[str, str] = {
    "goal_users": "目标用户与核心任务",
    "input_process_output": "输入、过程和产物",
    "main_loop": "Agent 主链路",
    "quality": "什么算生成得好",
    "delivery": "交付阶段与优先级",
    "model_cost": "模型与成本约束",
    "data_nonfunc": "数据与非功能要求",
    "launch": "上线与账号",
}

_STRIP_AFTER_TITLE = " ：:\t-—–"


def _is_pending_only(text: str) -> bool:
    t = text.strip()
    if not t:
        return True
    return t.lower() in {"待定", "tbd"}


def _normalize_one(title: str, value: object) -> str:
    raw = "" if value is None else str(value)
    text = raw.strip()
    if not text:
        return "待定"
    if text == title:
        return "待定"
    for sep in ("", "：", ":", " - ", "-", "—", "–", " "):
        if text == f"{title}{sep}待定":
            return "待定"
        if text.lower() == f"{title}{sep}tbd".lower():
            return "待定"
    rest = text
    if rest.startswith(title):
        rest = rest[len(title) :].lstrip(_STRIP_AFTER_TITLE)
        if _is_pending_only(rest):
            return "待定"
    if rest.startswith(title):
        rest2 = rest[len(title) :].lstrip(_STRIP_AFTER_TITLE)
        if _is_pending_only(rest2) or rest2 == "" or rest2 == title:
            return "待定"
    if _is_pending_only(text):
        return "待定"
    return text


def normalize_prd_fields(prd: dict) -> dict:
    """对每个字段：去空白；若正文等于标题、或「标题+待定」、或去掉标题后只剩待定/TBD，则改为「待定」。"""
    if not isinstance(prd, dict):
        return {}
    out: dict = {}
    for key, title in PRD_FIELD_TITLES.items():
        out[key] = _normalize_one(title, prd.get(key, ""))
    for key, val in prd.items():
        if key not in out:
            out[key] = val
    return out
