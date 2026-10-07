"""LLM 接口与工厂：mock（离线占位）与 deepseek（真实模型，OpenAI 兼容）。"""
from __future__ import annotations

import json
import logging
import time
from abc import ABC, abstractmethod
from pathlib import Path

from app.core.config import settings
from app.core.errors import AppError
from app.services import iteration, mock_llm, parsing
from app.services.prd_quality import PrdCompletenessError, validate_generated_prd

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
    def generate_prd(self, idea: str, decisions: list[dict], source_context: dict | None = None) -> dict: ...

    @abstractmethod
    def generate_code(self, idea: str, prd: dict, source_context: dict | None = None) -> dict[str, str]: ...

    def generate_acceptance_scenarios(self, idea: str, prd: dict) -> list[dict]:
        return mock_llm.generate_acceptance_scenarios(idea, prd)

    def agent_turn(self, role: str, messages: list[dict], tools: list[dict], context: dict) -> dict:
        """一次角色调用；执行器负责持久化预算，不在此方法内隐式重试。"""
        raise AppError("agent_tools_unavailable", "当前模型客户端不支持工具协作", 502)


class MockLLM(LLMClient):
    """离线占位，复用第 1 阶段 mock 生成函数。"""

    def __init__(self):
        super().__init__()

    def generate_clarify(self, idea: str) -> list[dict]:
        return mock_llm.generate_clarify(idea)

    def generate_prd(self, idea: str, decisions: list[dict], source_context: dict | None = None) -> dict:
        return mock_llm.generate_prd(idea, decisions, source_context=source_context)

    def generate_code(self, idea: str, prd: dict, source_context: dict | None = None) -> dict[str, str]:
        return mock_llm.generate_code(idea, prd, source_context=source_context)

    def agent_turn(self, role: str, messages: list[dict], tools: list[dict], context: dict) -> dict:
        # 模拟模型的可预测决策；读写、检查、权限与交接均经过真实执行器。
        results = [m for m in messages if m.get("role") == "tool"]
        if role == "builder":
            if not results:
                code = self.generate_code(context["idea"], context["prd"], context.get("source_context") or None)
                name, args = "write_files", {"files": {
                    "app.py": code["app"], "requirements.txt": code["requirements"], "README.md": code["readme"],
                }}
            elif len(results) == 1:
                name, args = "run_checks", {}
            else:
                name, args = "handoff", {"reason": "Mock 代码已提交，交给独立验证角色检查；业务效果仍待人工验收"}
        elif not results:
            name, args = "read_file", {"path": "app.py"}
        elif len(results) == 1:
            name, args = "run_checks", {}
        else:
            result = json.loads(results[-1]["content"])
            name, args = "conclude", {"passed": result.get("passed") is True, "summary": "Mock 根据真实工具检查给出技术结论，未评估真实业务效果"}
        return {"content": "", "tool_calls": [{"id": f"mock_{role}_{len(results) + 1}", "name": name, "arguments": args}]}


class RealLLM(LLMClient):
    """真实模型（OpenAI 兼容协议），带超时、有限重试与结构校验。"""

    def __init__(self):
        super().__init__()
        self.model = settings.llm_model
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
                    model=self.model,
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

    def agent_turn(self, role: str, messages: list[dict], tools: list[dict], context: dict) -> dict:
        """原生 SDK tools；禁用 SDK 自动重试，所有调用均占持久化的角色预算。"""
        try:
            response = self.client.with_options(max_retries=0).chat.completions.create(
                model=self.model, messages=messages, tools=tools, tool_choice="required",
                max_tokens=8000 if role == "builder" else 2500,
            )
        except Exception:
            raise AppError("agent_call_interrupted", "模型工具调用中断，可从已保存检查点继续", 502)
        usage = getattr(response, "usage", None)
        self.prompt_tokens += getattr(usage, "prompt_tokens", 0) or 0
        self.completion_tokens += getattr(usage, "completion_tokens", 0) or 0
        message = response.choices[0].message
        calls = []
        for call in message.tool_calls or []:
            try:
                arguments = json.loads(call.function.arguments)
            except (TypeError, ValueError):
                arguments = None
            calls.append({"id": call.id, "name": call.function.name, "arguments": arguments})
        return {"content": message.content or "", "tool_calls": calls}

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

    def generate_prd(self, idea: str, decisions: list[dict], source_context: dict | None = None) -> dict:
        # 保留问题、选项和推荐上下文；旧记录里的“按推荐”也要有实际含义。
        from app.services.decision_context import decision_model_context
        decisions_text = json.dumps([decision_model_context(d) for d in decisions], ensure_ascii=False)
        prompt = _load_prompt("prd.md").format(idea=idea, decisions=decisions_text)
        if source_context:
            prompt += (
                "\n\n这是对已有成品的修改。以下是创建子版本时保存的父 PRD 和完整源文件；"
                "以其为基础，只按本次修改与纠错更新范围，不把父成品当作空白项目。\n"
                "acceptance_results 是真实试用观察；其中 passed=false 的问题须作为改进和回归验收依据。\n"
                + json.dumps(source_context, ensure_ascii=False)
            )
        last_err: Exception | None = None
        for attempt in range(MAX_RETRIES + 1):
            repair_hint = ""
            if last_err is not None:
                detail = str(last_err)[:1600] if isinstance(last_err, PrdCompletenessError) else "JSON 结构或字段类型不符合合同"
                repair_hint = "\n\n上一次输出未通过检查，请重新输出完整 JSON，修正以下缺口：" + detail
            raw = self._chat(prompt + repair_hint, max_tokens=8000)
            try:
                return validate_generated_prd(parsing.parse_prd(raw))
            except Exception as exc:
                last_err = exc
        if isinstance(last_err, PrdCompletenessError):
            raise AppError("prd_content_incomplete", "PRD 缺少功能、页面或验收细节，请重试或补充需求", 502)
        raise AppError("llm_output_invalid", "模型输出格式校验失败，请重试", 502)

    def generate_code(self, idea: str, prd: dict, source_context: dict | None = None) -> dict[str, str]:
        prompt = _load_prompt("code.md").format(idea=idea, prd=str(prd))
        if source_context:
            prompt += (
                "\n\n本次必须基于下面父版本源文件实施修改，不得丢弃未要求改变的功能。"
                "遵循已确认的新 PRD 和业务验收场景；仍输出修改后的完整 APP/REQUIREMENTS/README 三块，"
                "不要输出补丁。父版本 acceptance_results 中的失败观察须结合修改要求修复。父版本上下文如下：\n"
                + json.dumps(source_context, ensure_ascii=False)
            )
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

    def generate_acceptance_scenarios(self, idea: str, prd: dict) -> list[dict]:
        prompt = _load_prompt("acceptance_scenarios.md").format(
            idea=idea, prd=json.dumps(prd, ensure_ascii=False),
        )
        for _ in range(MAX_RETRIES + 1):
            raw = self._chat(prompt, max_tokens=2500)
            try:
                data = parsing.parse_json(raw)
                if isinstance(data, dict):
                    data = data.get("scenarios")
                return iteration.validate_scenarios(data)
            except (TypeError, ValueError):
                continue
        raise AppError("llm_output_invalid", "业务验收场景生成失败，请重试", 502)


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
