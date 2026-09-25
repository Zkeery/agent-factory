"""度量采集与汇总：稳定出货率、平均耗时、平均成本、质量合格率。"""
from __future__ import annotations

import time

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import FactoryRun, RunMetric


def estimate_cost(prompt_tokens: int, completion_tokens: int) -> float:
    return (
        prompt_tokens / 1_000_000 * settings.cost_per_1m_input
        + completion_tokens / 1_000_000 * settings.cost_per_1m_output
    )


def record_metric(session: Session, run: FactoryRun, client, start_time: float) -> RunMetric:
    """运行每推进一段（到等待点或终态）就累加一次度量，最终为完整总耗时/token。"""
    duration = round(time.monotonic() - start_time, 2)
    prompt = getattr(client, "prompt_tokens", 0) or 0
    completion = getattr(client, "completion_tokens", 0) or 0
    metric = session.query(RunMetric).filter(RunMetric.run_id == run.id).first()
    if metric is None:
        metric = RunMetric(run_id=run.id, duration_seconds=0.0, prompt_tokens=0, completion_tokens=0, cost_estimate=0.0)
        session.add(metric)
    metric.duration_seconds = round(metric.duration_seconds + duration, 2)
    metric.prompt_tokens += prompt
    metric.completion_tokens += completion
    metric.cost_estimate = round(estimate_cost(metric.prompt_tokens, metric.completion_tokens), 6)
    session.commit()
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
    q = session.query(FactoryRun)
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
