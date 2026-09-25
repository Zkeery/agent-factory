"""产品项目 API：工作台左栏一等对象。"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.runs import get_session
from app.core.auth import get_current_user, require_api_key
from app.core.errors import AppError
from app.models import FactoryRun, ProductProject, User
from app.schemas import (
    CreateProjectRequest,
    ProjectListOut,
    ProjectOut,
    RunListOut,
    RunSummary,
    UpdateProjectRequest,
)

router = APIRouter(prefix="/api/v1", tags=["projects"], dependencies=[Depends(require_api_key)])


def _project_out(session: Session, project: ProductProject) -> ProjectOut:
    count = session.query(FactoryRun).filter(FactoryRun.project_id == project.id).count()
    return ProjectOut(
        id=project.id,
        name=project.name,
        idea_summary=project.idea_summary,
        workspace_path=project.workspace_path,
        created_at=project.created_at,
        updated_at=project.updated_at,
        run_count=count,
    )


def _project_or_404(session: Session, project_id: str, user: User) -> ProductProject:
    project = session.get(ProductProject, project_id)
    if project is None or project.user_id != user.id:
        raise AppError("project_not_found", "项目不存在", 404)
    return project


@router.get("/projects", response_model=ProjectListOut)
def list_projects(session: Session = Depends(get_session), user: User = Depends(get_current_user)):
    rows = (
        session.query(ProductProject)
        .filter(ProductProject.user_id == user.id)
        .order_by(ProductProject.updated_at.desc())
        .all()
    )
    return ProjectListOut(projects=[_project_out(session, p) for p in rows])


@router.post("/projects", response_model=ProjectOut, status_code=201)
def create_project(
    body: CreateProjectRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    project = ProductProject(
        id=str(uuid.uuid4()),
        user_id=user.id,
        name=body.name.strip() or "未命名项目",
        idea_summary=body.idea_summary.strip(),
        workspace_path=(body.workspace_path or "").strip(),
    )
    session.add(project)
    session.commit()
    session.refresh(project)
    return _project_out(session, project)


@router.get("/projects/{project_id}", response_model=ProjectOut)
def get_project(project_id: str, session: Session = Depends(get_session), user: User = Depends(get_current_user)):
    return _project_out(session, _project_or_404(session, project_id, user))


@router.patch("/projects/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: str,
    body: UpdateProjectRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    project = _project_or_404(session, project_id, user)
    if body.name is not None:
        project.name = body.name.strip() or project.name
    if body.idea_summary is not None:
        project.idea_summary = body.idea_summary.strip()
    if body.workspace_path is not None:
        project.workspace_path = body.workspace_path.strip()
    session.commit()
    session.refresh(project)
    return _project_out(session, project)


@router.get("/projects/{project_id}/runs", response_model=RunListOut)
def list_project_runs(project_id: str, session: Session = Depends(get_session), user: User = Depends(get_current_user)):
    _project_or_404(session, project_id, user)
    runs = (
        session.query(FactoryRun)
        .filter(FactoryRun.project_id == project_id, FactoryRun.user_id == user.id)
        .order_by(FactoryRun.created_at.desc())
        .all()
    )
    return RunListOut(
        runs=[
            RunSummary(
                id=r.id,
                idea=r.idea,
                current_stage=r.current_stage,
                status=r.status,
                created_at=r.created_at,
                project_id=r.project_id,
            )
            for r in runs
        ]
    )
