"""项目回收站的共享查询条件；历史运行与产物保留在原位置。"""
from sqlalchemy import or_, select

from app.models import FactoryRun, ProductProject


def active_run_filter():
    deleted_projects = select(ProductProject.id).where(ProductProject.deleted_at.is_not(None))
    return or_(FactoryRun.project_id.is_(None), FactoryRun.project_id.not_in(deleted_projects))
