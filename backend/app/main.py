"""Agent造物坊 后端入口：工厂内核（第 1 阶段）。"""
from __future__ import annotations

import logging
from pathlib import Path

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.auth import router as auth_router
from app.api.projects import router as projects_router
from app.api.runs import router as runs_router
from app.api.llm import router as llm_router
from app.api.schedules import router as schedules_router
from app.core.errors import register_error_handlers
from app.models import init_db
from app.services import scheduler, watchdog

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    watchdog.start_watchdog()
    scheduler.start_scheduler()
    yield


app = FastAPI(title="Agent造物坊", version="0.1.0", lifespan=lifespan)
register_error_handlers(app)
init_db()

# 允许前端（3010）直连后端，SSE 流式不被代理缓冲
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:3010", "http://localhost:3010"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(runs_router)
app.include_router(projects_router)
app.include_router(llm_router)
app.include_router(schedules_router)

STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")
