"""度量采集与汇总：稳定出货率、平均耗时、平均成本、质量合格率。"""
from __future__ import annotations

import json
import math
import threading
import time
import uuid
import weakref
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import FactoryRun, RunMetric
from app.services.project_lifecycle import active_run_filter

ACCOUNTING_VERSION = 1
_accounting_lock = threading.RLock()
_client_states: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


def pricing_snapshots(metric: RunMetric | None) -> list[dict]:
    try:
        entries = json.loads(metric.pricing_snapshots or "[]") if metric else []
        return [item for item in entries if isinstance(item, dict)] if isinstance(entries, list) else []
    except (ValueError, TypeError):
        return []


def configured_currency() -> str:
    """币种标签来自非秘密配置，不根据历史数值猜测汇率或货币。"""
    return (getattr(settings, "cost_currency", "USD") or "USD").strip().upper()


def run_source(run: FactoryRun, metric: RunMetric | None = None) -> str:
    """优先使用实际记账段；历史只依据持久化的提供方和模型快照。"""
    entries = pricing_snapshots(metric)
    if entries:
        sources = {item["source"] if isinstance(item.get("source"), str) else "unknown" for item in entries}
        if len(sources) == 1 and sources <= {"real", "mock"}:
            return next(iter(sources))
        return "unknown"  # 混合来源不能冒充纯真实运行。
    provider = (run.llm_provider or "").strip().lower()
    model = (run.llm_model_snapshot or "").strip().lower()
    if provider == "mock":
        return "mock" if model in {"", "mock"} else "unknown"
    if provider == "deepseek":
        return "unknown" if model == "mock" else "real"
    if provider:
        return "unknown"
    if model == "mock":
        return "mock"
    # 工厂只在确定实际模型后写此快照；不使用当前全局配置反推历史。
    return "real" if model and model not in {"unknown", "unavailable", "default"} else "unknown"


def _client_source(run: FactoryRun, client) -> str:
    # 本地导入避免服务模块初始化互相依赖；不读取 SDK 内部或配置密钥。
    from app.services.llm import MockLLM, RealLLM

    if isinstance(client, MockLLM):
        return "mock"
    if isinstance(client, RealLLM):
        return "real"
    return run_source(run)


def _number(value) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) and result >= 0 else 0.0
    except (TypeError, ValueError, OverflowError):
        return 0.0


def _price(value) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) and result >= 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def _client_checkpoint(client) -> dict:
    if client is None:
        return {"id": "no-client", "prompt": 0, "completion": 0}
    checkpoint = getattr(client, "_factory_accounting_checkpoint", None)
    if isinstance(checkpoint, dict):
        return checkpoint
    checkpoint = {"id": uuid.uuid4().hex, "prompt": 0, "completion": 0}
    try:
        setattr(client, "_factory_accounting_checkpoint", checkpoint)
    except (AttributeError, TypeError):
        # 支持只允许弱引用的客户端；正常 LLMClient 直接保存轻量游标。
        try:
            checkpoint = _client_states.setdefault(client, checkpoint)
        except TypeError:
            pass
    return checkpoint


def estimate_cost(prompt_tokens: int, completion_tokens: int) -> float:
    return (
        prompt_tokens / 1_000_000 * settings.cost_per_1m_input
        + completion_tokens / 1_000_000 * settings.cost_per_1m_output
    )


def record_metric(session: Session, run: FactoryRun, client, start_time: float, outcome: str = "completed") -> RunMetric:
    """每段只记增量 token 和当段价格；包含失败/取消，但不包含人工等待。"""
    with _accounting_lock:
        checkpoint = _client_checkpoint(client)
        segment_id = f"{checkpoint['id']}:{run.id}:{start_time}"
        metric = session.query(RunMetric).filter(RunMetric.run_id == run.id).order_by(RunMetric.id.asc()).first()
        if metric is None:
            metric = RunMetric(
                run_id=run.id, duration_seconds=0.0, prompt_tokens=0, completion_tokens=0,
                cost_estimate=0.0, pricing_snapshots="[]", accounting_version=0,
                recorded_segments=0, failed_segments=0,
            )
            session.add(metric)
        snapshots = pricing_snapshots(metric)
        if any(item.get("segment_id") == segment_id for item in snapshots):
            return metric
        if not snapshots and any(_number(value) > 0 for value in (
            metric.duration_seconds, metric.prompt_tokens, metric.completion_tokens, metric.cost_estimate,
        )):
            snapshots.append({
                "kind": "legacy", "version": 0, "source": run_source(run),
                "currency": None, "input_per_million": None, "output_per_million": None,
                "estimated_cost": metric.cost_estimate,
                "prompt_tokens": metric.prompt_tokens, "completion_tokens": metric.completion_tokens,
                "duration_seconds": metric.duration_seconds,
                "note": "历史记录未保存分段价格、币种或完整性，保留原值，不反推定价。",
            })
        total_prompt = int(_number(getattr(client, "prompt_tokens", 0)))
        total_completion = int(_number(getattr(client, "completion_tokens", 0)))
        prompt = total_prompt - checkpoint["prompt"] if total_prompt >= checkpoint["prompt"] else total_prompt
        completion = total_completion - checkpoint["completion"] if total_completion >= checkpoint["completion"] else total_completion
        duration = round(_number(time.monotonic() - start_time), 3)
        source = _client_source(run, client)
        unit_input = _price(settings.cost_per_1m_input)
        unit_output = _price(settings.cost_per_1m_output)
        currency = configured_currency()
        estimate = (round((prompt * unit_input + completion * unit_output) / 1_000_000, 8)
                    if source == "real" and unit_input is not None and unit_output is not None
                    else 0.0 if source == "mock" else None)
        snapshots.append({
            "kind": "segment", "version": ACCOUNTING_VERSION, "segment_id": segment_id,
            "recorded_at": datetime.now(timezone.utc).isoformat(), "source": source,
            "provider": (run.llm_provider or "").strip() or ("mock" if source == "mock" else "deepseek" if source == "real" else "unknown"),
            "model": run.llm_model_snapshot or ("mock" if source == "mock" else ""),
            "currency": currency, "input_per_million": unit_input if source == "real" else None,
            "output_per_million": unit_output if source == "real" else None,
            "prompt_tokens": prompt, "completion_tokens": completion,
            "estimated_cost": estimate, "duration_seconds": duration,
            "outcome": outcome if outcome in {"completed", "failed", "cancelled"} else "unknown",
            "usage_basis": "reported_tokens_only",
        })
        metric.duration_seconds = round(_number(metric.duration_seconds) + duration, 3)
        metric.prompt_tokens = int(_number(metric.prompt_tokens)) + prompt
        metric.completion_tokens = int(_number(metric.completion_tokens)) + completion
        metric.cost_estimate = round(_number(metric.cost_estimate) + (estimate or 0.0), 8)
        metric.pricing_snapshots = json.dumps(snapshots, ensure_ascii=False)
        metric.accounting_version = max(metric.accounting_version or 0, ACCOUNTING_VERSION)
        metric.recorded_segments = (metric.recorded_segments or 0) + 1
        metric.failed_segments = (metric.failed_segments or 0) + int(outcome == "failed")
        session.commit()
        # 只有数据库提交成功后才前移游标，重试不会丢失已返回的 usage。
        checkpoint["prompt"] = total_prompt
        checkpoint["completion"] = total_completion
        return metric


def score_run(session: Session, run_id: str, decision: int, prd: int, code: int) -> RunMetric:
    """产品经理打三维分；重复打分覆盖。"""
    metric = session.query(RunMetric).filter(RunMetric.run_id == run_id).first()
    if metric is None:
        metric = RunMetric(run_id=run_id, duration_seconds=0.0)
        session.add(metric)
    metric.score_decision = decision
    metric.score_prd = prd
    metric.score_code = code
    session.commit()
    return metric


def summarize(session: Session, user_id: str | None = None) -> dict:
    """汇总四个核心数字（按用户隔离；user_id=None 时看全部）。质量合格线：三维均 ≥2 分。"""
    q = session.query(FactoryRun).filter(active_run_filter())
    if user_id is not None:
        q = q.filter(FactoryRun.user_id == user_id)
    runs = q.all()
    run_ids = {r.id for r in runs}
    metrics_map = (
        {m.run_id: m for m in session.query(RunMetric).filter(RunMetric.run_id.in_(run_ids)).all()}
        if run_ids
        else {}
    )
    total = len(runs)
    if total == 0:
        return {
            "total_runs": 0,
            "ship_rate": 0.0,
            "avg_duration": 0.0,
            "avg_cost": 0.0,
            "quality_rate": None,
            "scored_runs": 0,
        }
    shipped = sum(1 for r in runs if r.current_stage == "delivered")
    durations = [m.duration_seconds for m in metrics_map.values() if m.duration_seconds > 0]
    costs = [m.cost_estimate for m in metrics_map.values()]
    scored = [
        m for m in metrics_map.values()
        if m.score_decision is not None and m.score_prd is not None and m.score_code is not None
    ]
    qualified = [
        m for m in scored
        if min(m.score_decision, m.score_prd, m.score_code) >= 2
    ]
    return {
        "total_runs": total,
        "ship_rate": round(shipped / total, 4),
        "avg_duration": round(sum(durations) / len(durations), 2) if durations else 0.0,
        "avg_cost": round(sum(costs) / len(costs), 6) if costs else 0.0,
        "quality_rate": round(len(qualified) / len(scored), 4) if scored else None,
        "scored_runs": len(scored),
    }
