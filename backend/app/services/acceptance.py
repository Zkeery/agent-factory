"""验收清单：对齐 PRD §4.1 MVP 成功定义的主路径人工勾选。"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChecklistItemDef:
    id: str
    label: str


# 与前端 DEFAULT_ACCEPTANCE_CHECKLIST 保持同 id / 文案
DEFAULT_ACCEPTANCE_CHECKLIST: tuple[ChecklistItemDef, ...] = (
    ChecklistItemDef("local_run", "主路径能按说明在本地跑起来"),
    ChecklistItemDef("prd_match", "PRD 与实现大体一致"),
    ChecklistItemDef("no_blockers", "没有明显阻断性错误"),
)

REQUIRED_IDS = frozenset(item.id for item in DEFAULT_ACCEPTANCE_CHECKLIST)


def validate_acceptance_checklist(items: list) -> None:
    """校验请求清单：必须覆盖全部必选项且全部 passed。

    items: 具有 .id / .passed 属性的对象列表（Pydantic model 即可）。
    失败时抛出 ValueError，message 为对人可读原因；调用方映射为 AppError。
    """
    if not items:
        raise ValueError("请勾选验收清单全部项后再交付")
    by_id = {getattr(i, "id", None): i for i in items}
    missing = REQUIRED_IDS - set(by_id)
    if missing:
        raise ValueError("验收清单不完整，请勾选全部必选项")
    failed = [by_id[i] for i in REQUIRED_IDS if not getattr(by_id[i], "passed", False)]
    if failed:
        raise ValueError("验收清单尚有未通过项")
