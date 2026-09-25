"""pytest 配置：在导入 app 前指向独立测试库，每个测试重置表。"""
from __future__ import annotations

import os
from pathlib import Path

TEST_DB = Path(__file__).resolve().parents[1] / "data" / "test_factory.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"
# 测试固定用 mock，不读 .env 的真实模型配置，不花真钱、不依赖网络
os.environ["LLM_PROVIDER"] = "mock"
os.environ["LLM_API_KEY"] = ""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import Base, SessionLocal, engine


@pytest.fixture(autouse=True)
def clean_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture()
def client():
    with TestClient(app) as c:
        # 自动登录（mock 短信），给所有接口测试带上默认鉴权头
        r = c.post("/api/v1/auth/request-code", json={"phone": "13800138000"})
        code = r.json()["mock_code"]
        r = c.post("/api/v1/auth/login", json={"phone": "13800138000", "code": code})
        c.headers["Authorization"] = f"Bearer {r.json()['token']}"
        yield c


@pytest.fixture()
def session():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()
