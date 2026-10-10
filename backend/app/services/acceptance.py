"""验收清单：对齐 PRD §4.1 MVP 成功定义的主路径人工勾选。"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChecklistItemDef:
    id: str
    label: str


# 与前端 DEFAULT_ACCEPTANCE_CHECKLIST 保持同 id / 文案。
# 历史清单里的 prd_match、no_blockers 仍可保存，交付只要求主流程这一项。
DEFAULT_ACCEPTANCE_CHECKLIST: tuple[ChecklistItemDef, ...] = (
    ChecklistItemDef("local_run", "主流程走通了"),
)

REQUIRED_IDS = frozenset(item.id for item in DEFAULT_ACCEPTANCE_CHECKLIST)


def validate_acceptance_checklist(items: list) -> None:
    """交付只要求主流程通过。历史清单里的其他项不阻断。

    items: 具有 .id / .passed 属性的对象列表（Pydantic model 即可）。
    失败时抛出 ValueError，message 为对人可读原因；调用方映射为 AppError。
    """
    if not items:
        raise ValueError("请确认主流程走通后再交付")
    by_id = {getattr(i, "id", None): i for i in items}
    missing = REQUIRED_IDS - set(by_id)
    if missing:
        raise ValueError("请确认主流程走通后再交付")
    failed = [by_id[i] for i in REQUIRED_IDS if not getattr(by_id[i], "passed", False)]
    if failed:
        raise ValueError("主流程未通过，不能交付")
