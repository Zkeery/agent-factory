"""工作区写盘授权与同步（第八刀，PRD §8）。"""
from __future__ import annotations

import shutil
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import FactoryRun, ProductProject
from app.services.runner import _code_dir
from app.services.stages import Stage

PREVIEW_STAGES = {
    Stage.GATE_PASSED.value,
    Stage.AWAITING_ACCEPTANCE.value,
    Stage.DELIVERED.value,
}
ALLOWED_SCOPES = {"write", "exec"}


def ensure_exec_authorized(run: FactoryRun) -> None:
    if run.workspace_always_allow or run.workspace_exec_authorized:
        return
    raise AppError("workspace_exec_required", "请先确认后再启动本地预览", 403)


def ensure_write_authorized(run: FactoryRun) -> None:
    if run.workspace_always_allow or run.workspace_write_authorized:
        return
    raise AppError("workspace_write_required", "请先确认后再同步到工作区", 403)


def authorize(
    session: Session,
    run: FactoryRun,
    *,
    scopes: list[str],
    always_for_run: bool,
    role: str,
) -> FactoryRun:
    role = (role or "pm").strip().lower()
    if role not in {"pm", "dev"}:
        raise AppError("invalid_role", "role 只能是 pm 或 dev", 400)
    if always_for_run and role != "dev":
        raise AppError("always_not_allowed_for_pm", "产品经理不能勾选「本 Run 始终允许」", 400)

    cleaned: list[str] = []
    for s in scopes or []:
        s = (s or "").strip().lower()
        if s not in ALLOWED_SCOPES:
            raise AppError("invalid_scope", f"未知授权范围：{s}", 400)
        if s not in cleaned:
            cleaned.append(s)
    if not cleaned and not always_for_run:
        raise AppError("scopes_required", "scopes 至少包含 write 或 exec 之一", 400)

    if always_for_run:
        run.workspace_always_allow = True
        run.workspace_write_authorized = True
        run.workspace_exec_authorized = True
    else:
        if "write" in cleaned:
            run.workspace_write_authorized = True
        if "exec" in cleaned:
            run.workspace_exec_authorized = True

    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def _resolve_target(raw: str) -> Path:
    path = (raw or "").strip()
    if not path:
        raise AppError("workspace_path_required", "项目尚未绑定工作区路径", 400)
    p = Path(path).expanduser()
    if not p.is_absolute():
        raise AppError("workspace_path_invalid", "工作区路径必须是绝对路径", 400)
    if "\x00" in path:
        raise AppError("workspace_path_invalid", "工作区路径非法", 400)
    return p.resolve()


def sync_to_workspace(session: Session, run: FactoryRun) -> dict:
    if run.current_stage not in PREVIEW_STAGES:
        raise AppError("not_ready", "成品尚未生成完成，不能同步到工作区", 409)
    ensure_write_authorized(run)

    if not run.project_id:
        raise AppError("project_required", "当前运行未关联项目，无法同步工作区", 400)
    project = session.get(ProductProject, run.project_id)
    if project is None:
        raise AppError("project_not_found", "项目不存在", 404)

    target = _resolve_target(project.workspace_path)
    target.mkdir(parents=True, exist_ok=True)

    src = _code_dir(run.id)
    if not src.is_dir():
        raise AppError("code_not_found", "本轮生成代码目录不存在", 404)

    files_copied = 0
    for item in src.iterdir():
        if not item.is_file():
            continue
        dest = (target / item.name).resolve()
        if not dest.is_relative_to(target):
            raise AppError("workspace_path_invalid", f"拒绝写入越界文件：{item.name}", 400)
        shutil.copy2(item, dest)
        files_copied += 1

    if files_copied == 0:
        raise AppError("code_not_found", "本轮没有可同步的代码文件", 404)

    return {"ok": True, "target": str(target), "files_copied": files_copied}
