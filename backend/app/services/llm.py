"""LLM 接口与工厂：mock（离线占位）与 deepseek（真实模型，OpenAI 兼容）。"""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from pathlib import Path

from app.core.config import settings
from app.core.errors import AppError
from app.services import mock_llm, parsing

logger = logging.getLogger("factory.llm")
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

MAX_RETRIES = 2  # 结构校验失败最多重试次数


def _load_prompt(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


class LLMClient(ABC):
    def __init__(self):
        self.prompt_tokens = 0
        self.completion_tokens = 0

    @abstractmethod
    def generate_clarify(self, idea: str) -> list[dict]: ...

    @abstractmethod
    def generate_prd(self, idea: str, decisions: list[dict]) -> dict: ...

    @abstractmethod
    def generate_code(self, idea: str, prd: dict) -> dict[str, str]: ...


class MockLLM(LLMClient):
    """离线占位，复用第 1 阶段 mock 生成函数。"""

    def __init__(self):
        super().__init__()

    def generate_clarify(self, idea: str) -> list[dict]:
        return mock_llm.generate_clarify(idea)

    def generate_prd(self, idea: str, decisions: list[dict]) -> dict:
        return mock_llm.generate_prd(idea, decisions)

    def generate_code(self, idea: str, prd: dict) -> dict[str, str]:
        return mock_llm.generate_code(idea, prd)


class RealLLM(LLMClient):
    """真实模型（OpenAI 兼容协议），带超时、有限重试与结构校验。"""

    def __init__(self):
        super().__init__()
        if not settings.llm_api_key:
            raise AppError("llm_key_missing", "缺少模型 API Key，请在 .env 填写 LLM_API_KEY", 500)
        try:
            from openai import OpenAI
        except ImportError:
            raise AppError("llm_sdk_missing", "缺少 openai 依赖", 500)
        self.client = OpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url, timeout=settings.llm_timeout)

    def _chat(self, prompt: str, max_tokens: int = 2000) -> str:
        for attempt in range(MAX_RETRIES + 1):
            start = time.monotonic()
            try:
                resp = self.client.chat.completions.create(
                    model=settings.llm_model,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=max_tokens,
                )
                content = (resp.choices[0].message.content or "").strip()
                usage = getattr(resp, "usage", None)
                self.prompt_tokens += getattr(usage, "prompt_tokens", 0) or 0
                self.completion_tokens += getattr(usage, "completion_tokens", 0) or 0
                logger.info(
                    "模型调用完成 model=%s 耗时=%.2fs tokens=%s",
                    settings.llm_model,
                    time.monotonic() - start,
                    usage,
                )
                return content
            except Exception as exc:
                logger.warning("模型调用失败(第 %d 次)：%s", attempt + 1, type(exc).__name__)  # 不记录 Key 与敏感原文
                if attempt >= MAX_RETRIES:
                    raise AppError("llm_call_failed", "模型调用失败，请稍后重试", 502)
                time.sleep(1.5 * (attempt + 1))
        raise AppError("llm_call_failed", "模型调用失败，请稍后重试", 502)

    def generate_clarify(self, idea: str) -> list[dict]:
        prompt = _load_prompt("clarify.md").format(idea=idea)
        last_err: Exception | None = None
        for _ in range(MAX_RETRIES + 1):
            raw = self._chat(prompt)
            try:
                return parsing.parse_clarify(raw)
            except Exception as exc:
                last_err = exc
        raise AppError("llm_output_invalid", "模型输出格式校验失败，请重试", 502)

    def generate_prd(self, idea: str, decisions: list[dict]) -> dict:
        decisions_text = "\n".join(
            f"- {d.get('code', '')}：{d.get('question', '')} → {d.get('answer', '未答')}" for d in decisions
        )
        prompt = _load_prompt("prd.md").format(idea=idea, decisions=decisions_text)
        last_err: Exception | None = None
        for _ in range(MAX_RETRIES + 1):
            raw = self._chat(prompt)
            try:
                return parsing.parse_prd(raw)
            except Exception as exc:
                last_err = exc
        raise AppError("llm_output_invalid", "模型输出格式校验失败，请重试", 502)

    def generate_code(self, idea: str, prd: dict) -> dict[str, str]:
        prompt = _load_prompt("code.md").format(idea=idea, prd=str(prd))
        last_err: Exception | None = None
        for _ in range(MAX_RETRIES + 1):
            # 代码三块（app/requirements/readme）较长，用更大输出上限，
            # 避免 2000 token 截断导致三块不完整而校验失败
            raw = self._chat(prompt, max_tokens=8000)
            try:
                return parsing.parse_code(raw)
            except Exception as exc:
                last_err = exc
        raise AppError("llm_output_invalid", "代码生成格式校验失败，请重试", 502)


def resolve_provider(override: str | None = None) -> str:
    """空/None 跟随全局 settings；显式 mock/deepseek 覆盖。"""
    raw = (override if override is not None else "")
    p = raw.strip().lower() if isinstance(raw, str) else ""
    if not p:
        p = settings.llm_provider.strip().lower()
    if p not in ("mock", "deepseek"):
        raise AppError("unknown_llm_provider", f"未知模型提供商：{p or '(empty)'}", 400)
    return p


def provider_model_label(provider: str) -> str:
    p = resolve_provider(provider)
    if p == "mock":
        return "mock"
    return settings.llm_model


def list_llm_profiles() -> dict:
    """可供前端选择的画像；永不回显 API Key。"""
    default_provider = settings.llm_provider.strip().lower() or "mock"
    deepseek_ok = bool(settings.llm_api_key.strip())
    return {
        "default_provider": default_provider if default_provider in ("mock", "deepseek") else "mock",
        "profiles": [
            {"id": "mock", "label": "本地 Mock（零成本）", "available": True, "model": "mock"},
            {
                "id": "deepseek",
                "label": "DeepSeek（.env）",
                "available": deepseek_ok,
                "model": settings.llm_model,
            },
        ],
    }


def get_llm(provider: str | None = None) -> LLMClient:
    p = resolve_provider(provider)
    if p == "mock":
        return MockLLM()
    if p == "deepseek":
        return RealLLM()
    raise AppError("unknown_llm_provider", f"未知模型提供商：{p}", 500)
