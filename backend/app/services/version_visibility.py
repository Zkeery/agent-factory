"""项目版本列表的可见性。

用户对失败或闸门失败的版本做整段重跑并成功创建新版本后，旧版本从列表、
版本数中隐藏。记录、父子关联和复盘统计仍保留。已取消、修改版、定时创建
和就地重测都不走这条隐藏。
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import FactoryRun

REPLACED_FAILURE_STAGES = frozenset({"failed", "gate_failed"})


def visible_version_filter():
    """版本列表与版本计数使用。复盘和指标不要套用这个条件。"""
    return FactoryRun.superseded_by_run_id.is_(None)


def next_version_no(session: Session, project_id: str | None) -> int:
    """项目内序号只增不减。没有项目归属的历史运行各自显示为 V1。"""
    if not project_id:
        return 1
    current = session.query(func.max(FactoryRun.version_no)).filter(FactoryRun.project_id == project_id).scalar()
    return int(current or 0) + 1


def mark_replaced_failure(old: FactoryRun, new: FactoryRun, when: datetime | None = None) -> bool:
    """新版本已经组装成功后，把被重跑的失败版本标成不再展示。"""
    if old.current_stage not in REPLACED_FAILURE_STAGES or not new.id or new.id == old.id:
        return False
    old.superseded_by_run_id = new.id
    old.superseded_at = when or datetime.now(timezone.utc)
    return True


def _lineage_key(run: FactoryRun) -> tuple:
    return (
        run.project_id or "",
        run.user_id or "",
        run.idea or "",
        run.parent_run_id or "",
        run.change_request or "",
        run.parent_context or "{}",
        run.requirement_feedback or "[]",
        run.acceptance_mode or "basic",
        run.execution_mode or "workflow",
        run.llm_provider or "",
        run.llm_model_snapshot or "",
    )


def assign_missing_version_numbers(session: Session) -> None:
    """按创建顺序补齐尚未编号的运行。已经写过的序号保持不变。"""
    runs = session.query(FactoryRun).order_by(FactoryRun.created_at.asc(), FactoryRun.id.asc()).all()
    grouped: dict[str | None, list[FactoryRun]] = defaultdict(list)
    for run in runs:
        grouped[run.project_id].append(run)
    for project_id, items in grouped.items():
        if not project_id:
            for run in items:
                if not run.version_no:
                    run.version_no = 1
            continue
        numbered = [run.version_no for run in items if run.version_no]
        if not numbered:
            for index, run in enumerate(items, start=1):
                run.version_no = index
            continue
        nxt = max(numbered)
        for run in items:
            if not run.version_no:
                nxt += 1
                run.version_no = nxt


def backfill_replaced_failures(session: Session) -> int:
    """升级时把已经重跑过的失败版本标成隐藏。

    整段重跑会复制想法、父版本、修改要求和执行配置，且不带定时标记或修改提交号。
    同一谱系里，后出现的这种运行替代更早的失败版本。修改版、定时运行和未重跑的失败不隐藏。
    """
    runs = session.query(FactoryRun).order_by(FactoryRun.created_at.asc(), FactoryRun.id.asc()).all()
    open_failures: dict[tuple, list[FactoryRun]] = defaultdict(list)
    linked = 0
    for run in runs:
        if run.superseded_by_run_id:
            continue
        key = _lineage_key(run)
        retry_shape = not run.auto_schedule_id and not run.revision_request_id
        pending = open_failures.get(key) or []
        if retry_shape and pending:
            target = pending.pop(0)
            if target.id != run.id and mark_replaced_failure(target, run, run.created_at):
                linked += 1
        if run.current_stage in REPLACED_FAILURE_STAGES and not run.superseded_by_run_id:
            open_failures[key].append(run)
    return linked
