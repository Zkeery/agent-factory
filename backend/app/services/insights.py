"""本用户的项目展示与复盘；缺测量或无可比基线时不生成改善数字。"""
from __future__ import annotations

import json
import math
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import FactoryRun, ProductProject, RunMetric, StageEvent
from app.services.project_lifecycle import active_run_filter
from app.services.metrics import configured_currency, pricing_snapshots, run_source
from app.services.version_visibility import visible_parent_ids

SOURCES = {"real", "mock", "unknown", "all"}
DAYS = {"7", "30", "90", "all"}
FAILED_STAGES = {"failed", "gate_failed"}


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _json(raw, expected: type):
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
        return value if isinstance(value, expected) else expected()
    except (TypeError, ValueError):
        return expected()


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def _metric(value, samples: int, excluded: int, definition: str, numerator=None, denominator=None) -> dict:
    return {"value": value, "numerator": numerator, "denominator": denominator,
            "samples": samples, "excluded": excluded, "definition": definition}


def _ratio(numerator: int, denominator: int, excluded: int, definition: str) -> dict:
    return _metric(round(numerator / denominator, 4) if denominator else None,
                   denominator, excluded, definition, numerator, denominator)


def _median(values: list[float], total: int, definition: str) -> dict:
    return _metric(round(statistics.median(values), 3) if values else None, len(values), total - len(values), definition)


def _accounted(metric: RunMetric | None) -> bool:
    if metric is None or (metric.accounting_version or 0) < 1:
        return False
    snapshots = pricing_snapshots(metric)
    return bool(snapshots) and metric.recorded_segments == len(snapshots) and all(
        item.get("kind") == "segment" and isinstance(item.get("version"), int) and item["version"] >= 1
        and _finite(item.get("duration_seconds")) for item in snapshots
    )


def _execution_seconds(metric: RunMetric | None) -> float | None:
    if not _accounted(metric):
        return None
    return round(sum(item["duration_seconds"] for item in pricing_snapshots(metric)), 3)


def _cost(metric: RunMetric | None, source: str, currency: str) -> float | None:
    if metric is None or source == "unknown":
        return None
    if source == "mock":
        return 0.0  # Mock 没有真实模型费用，不沿用旧版的通用 token 单价。
    if not _accounted(metric):
        return None
    snapshots = pricing_snapshots(metric)
    if any(item.get("source") != "real" or item.get("currency") != currency
           or not _finite(item.get("estimated_cost"))
           or not _finite(item.get("input_per_million"))
           or not _finite(item.get("output_per_million")) for item in snapshots):
        return None
    return round(sum(item["estimated_cost"] for item in snapshots), 8)


def _check_result(payload: str) -> bool | None:
    text = (payload or "").strip().lower()
    if text == "passed":
        return True
    if text == "failed" or text.startswith("failed:"):
        return False
    value = _json(payload, dict)
    if isinstance(value.get("passed"), bool):
        return value["passed"]
    for key in ("status", "result"):
        if isinstance(value.get(key), str) and value[key] in {"passed", "failed"}:
            return value[key] == "passed"
    return None


def _fingerprint(scenario: dict) -> tuple[str, str] | None:
    values = (scenario.get("input"), scenario.get("expected_output"))
    if not all(isinstance(value, str) and value.strip() for value in values):
        return None
    return tuple(value.replace("\r\n", "\n").strip() for value in values)


def _scenario_index(scenarios: list) -> dict:
    index = defaultdict(list)
    for scenario in scenarios:
        if isinstance(scenario, dict) and (fingerprint := _fingerprint(scenario)):
            index[fingerprint].append(scenario)
    return index


def _observations(raw) -> dict:
    entries = _json(raw, list)
    grouped = defaultdict(list)
    for item in entries:
        if isinstance(item, dict) and isinstance(item.get("scenario_id"), str):
            grouped[item["scenario_id"]].append(item)
    return {key: items[0] for key, items in grouped.items() if len(items) == 1
            and isinstance(items[0].get("passed"), bool)
            and isinstance(items[0].get("observation"), str) and items[0]["observation"].strip()}


def _iteration_review(runs: list[FactoryRun], parents: dict, sources: dict, parent_sources: dict) -> tuple[dict, int]:
    counts = {"baseline_failed": 0, "comparable": 0, "fixed": 0, "pending": 0, "excluded": 0, "new_failures": 0}
    missing_baselines = 0
    for run in runs:
        if not run.parent_run_id:
            continue
        context = _json(run.parent_context, dict)
        baseline_scenarios = _json(context.get("acceptance_scenarios"), list)
        baseline_results = _observations(context.get("acceptance_results"))
        if not baseline_scenarios or not baseline_results:
            missing_baselines += 1
            continue
        old_index = _scenario_index(baseline_scenarios)
        new_scenarios = _json(run.acceptance_scenarios, list)
        new_index = _scenario_index(new_scenarios)
        new_results = _observations(run.acceptance_results)
        # 父记录必须仍属于本用户；跨来源或来源不明不用于声称改进。
        same_source = run.parent_run_id in parents and sources[run.id] in {"real", "mock"} and parent_sources.get(run.parent_run_id) == sources[run.id]
        for old in baseline_scenarios:
            if not isinstance(old, dict):
                continue
            observation = baseline_results.get(old.get("id"))
            if observation is None or observation["passed"]:
                continue
            counts["baseline_failed"] += 1
            fingerprint = _fingerprint(old)
            matches = new_index.get(fingerprint, [])
            if not same_source or not fingerprint or len(old_index.get(fingerprint, [])) != 1 or len(matches) != 1:
                counts["excluded"] += 1
                continue
            result = new_results.get(matches[0].get("id"))
            if result is None:
                counts["pending"] += 1
                continue
            counts["comparable"] += 1
            counts["fixed"] += int(result["passed"])
        if not same_source:
            continue
        for current in new_scenarios:
            if not isinstance(current, dict):
                continue
            result = new_results.get(current.get("id"))
            fingerprint = _fingerprint(current)
            if result is None or result["passed"] or not fingerprint or len(new_index[fingerprint]) != 1:
                continue
            matches = old_index.get(fingerprint, [])
            old_result = baseline_results.get(matches[0].get("id")) if len(matches) == 1 else None
            if not matches or (old_result is not None and old_result["passed"]):
                counts["new_failures"] += 1
    return counts, missing_baselines


def _metric_map(session: Session, run_ids: set[str]) -> tuple[dict[str, RunMetric | None], int]:
    grouped = defaultdict(list)
    if run_ids:
        for metric in session.query(RunMetric).filter(RunMetric.run_id.in_(run_ids)).all():
            grouped[metric.run_id].append(metric)
    # 旧库未约束唯一性；不任选一条或把可能重复的累计值再次相加。
    return ({key: records[0] if len(records) == 1 else None for key, records in grouped.items()},
            sum(len(records) > 1 for records in grouped.values()))


def build_review(session: Session, user_id: str, *, source: str = "real", days: str = "all",
                 project_id: str | None = None, now: datetime | None = None) -> dict:
    if source not in SOURCES or days not in DAYS:
        raise AppError("invalid_review_filter", "source 须为 real/mock/unknown/all；days 须为 7/30/90/all", 400)
    if project_id is not None:
        project = session.get(ProductProject, project_id)
        if project is None or project.user_id != user_id or project.deleted_at is not None:
            raise AppError("project_not_found", "项目不存在", 404)
    now = _utc(now or datetime.now(timezone.utc))
    query = session.query(FactoryRun).filter(FactoryRun.user_id == user_id, FactoryRun.created_at <= now, active_run_filter())
    if days != "all":
        query = query.filter(FactoryRun.created_at >= now - timedelta(days=int(days)))
    if project_id is not None:
        query = query.filter(FactoryRun.project_id == project_id)
    cohort = query.order_by(FactoryRun.created_at.desc(), FactoryRun.id.asc()).all()
    metric_map, duplicate_metrics = _metric_map(session, {run.id for run in cohort})
    sources = {run.id: run_source(run, metric_map.get(run.id)) for run in cohort}
    runs = [run for run in cohort if source == "all" or sources[run.id] == source]
    counts = {"total": len(runs), "delivered": 0, "failed": 0, "cancelled": 0, "pending": 0,
              "real": 0, "mock": 0, "unknown": 0}
    rows = []
    currency = configured_currency()
    interrupted_count = 0
    for run in runs:
        counts[sources[run.id]] += 1
        status = "delivered" if run.current_stage == "delivered" else "failed" if run.current_stage in FAILED_STAGES else "cancelled" if run.current_stage == "cancelled" else "pending"
        counts[status] += 1
        created = _utc(run.created_at)
        accepted = _utc(run.accepted_at) if run.accepted_at else None
        delivery_seconds = round((accepted - created).total_seconds(), 3) if status == "delivered" and accepted and created <= accepted <= now else None
        metric = metric_map.get(run.id)
        accounting_incomplete = _json(run.execution_state, dict).get("accounting_incomplete") is True
        interrupted_count += int(accounting_incomplete)
        rows.append({
            "run_id": run.id, "project_id": run.project_id, "idea": run.idea,
            "stage": run.current_stage, "source": sources[run.id],
            "execution_mode": run.execution_mode or "workflow", "created_at": created,
            "accepted_at": accepted, "delivery_seconds": delivery_seconds,
            "execution_seconds": None if accounting_incomplete else _execution_seconds(metric),
            "estimated_cost": None if accounting_incomplete else _cost(metric, sources[run.id], currency),
            "accounting_version": metric.accounting_version or 0 if metric else 0,
            "parent_run_id": run.parent_run_id,
        })
    run_ids = {run.id for run in runs}
    latest_checks = {}
    if run_ids:
        events = session.query(StageEvent).filter(
            StageEvent.run_id.in_(run_ids), StageEvent.event_type == "test_result", StageEvent.created_at <= now,
        ).order_by(StageEvent.id.desc()).all()
        for event in events:
            if event.run_id not in latest_checks:
                latest_checks[event.run_id] = _check_result(event.payload)
    checks = [value for value in latest_checks.values() if value is not None]
    parent_ids = {run.parent_run_id for run in runs if run.parent_run_id}
    parents = {run.id: run for run in session.query(FactoryRun).filter(
        FactoryRun.id.in_(parent_ids), FactoryRun.user_id == user_id, active_run_filter(),
    ).all()} if parent_ids else {}
    parent_metrics, _ = _metric_map(session, set(parents))
    parent_sources = {key: run_source(run, parent_metrics.get(key)) for key, run in parents.items()}
    iteration, missing_baselines = _iteration_review(runs, parents, sources, parent_sources)
    terminal = counts["delivered"] + counts["failed"] + counts["cancelled"]
    delivery_values = [row["delivery_seconds"] for row in rows if row["delivery_seconds"] is not None]
    execution_values = [row["execution_seconds"] for row in rows if row["execution_seconds"] is not None]
    costs = [row["estimated_cost"] for row in rows if row["estimated_cost"] is not None]
    notes = [
        "统计按 Run 创建时间选队列，使用 UTC 滚动时间窗，起止时刻均包含；结果截至 generated_at。每个版本是一条 Run。",
        "执行耗时不含人工等待；交付耗时包含等待，仅有有效验收时间的已交付样本参与。尚未结束的 Run 不进交付率分母。",
        "成本仅按模型返回的已记录 token 和当段配置单价估算；未返回 usage 的调用不计，不代表供应商实际账单。",
        "迭代按父子版本对计数，以输入和预期结果一致为可比条件；同 ID 改任务不算修复。无基线或未复验不视为改善。",
        "新增失败指父版已通过的同场景或本版新增场景出现失败观察；父版未验证的场景不作退步判断。",
        "不计算生成应用内部业务收益，也不将自动检查通过视为人工验收通过。",
    ]
    if len(cohort) != len(runs):
        notes.append(f"来源筛选排除了 {len(cohort) - len(runs)} 条其他来源 Run；counts 和所有分母均基于筛选后的队列。")
    if source == "all" and sum(counts[key] > 0 for key in ("real", "mock", "unknown")) > 1:
        notes.append("当前展示混合来源总量；请切到真实模型查看真实运行成效，不可将演示样本解释为真实改善。")
    if counts["unknown"]:
        notes.append(f"{counts['unknown']} 条 Run 来源未知或混合，不从当前全局模型配置反推来源，也不估算其成本。")
    if len(costs) < len(runs):
        notes.append(f"{len(runs) - len(costs)} 条 Run 缺少可追溯定价、来源或同币种完整记录，未计入成本合计；缺失值不是零费用。")
    if len(execution_values) < len(runs):
        notes.append(f"{len(runs) - len(execution_values)} 条 Run 缺少新版完整分段计时，未计入执行耗时中位数；历史计时不与新版混作改善。")
    if interrupted_count:
        notes.append(f"{interrupted_count} 条 Run 曾异常中断，无法保证完整记账，未计入执行耗时及成本；交付经过时间仍按创建和验收时间计算。")
    if counts["delivered"] > len(delivery_values):
        notes.append(f"{counts['delivered'] - len(delivery_values)} 条已交付 Run 缺少有效验收时间，未计入交付耗时。")
    if missing_baselines:
        notes.append(f"{missing_baselines} 条修改版缺少父快照中的实际观察，未生成迭代效果结论。")
    if duplicate_metrics:
        notes.append(f"队列内 {duplicate_metrics} 条 Run 存在多条累计度量记录，未任选或相加，以免重复计数。")
    shown_rows = [row for row, run in zip(rows, runs) if not run.superseded_by_run_id]
    hidden_from_list = len(rows) - len(shown_rows)
    if hidden_from_list:
        notes.append(f"{hidden_from_list} 条已被整段重跑替代的失败版本仍计入上方统计，不再列入版本记录。")
    resolved_parents = visible_parent_ids(session, [row["parent_run_id"] for row in shown_rows])
    for row in shown_rows:
        if row["parent_run_id"]:
            row["parent_run_id"] = resolved_parents.get(row["parent_run_id"], row["parent_run_id"])
    rows = shown_rows
    return {
        "generated_at": now, "filters": {"source": source, "days": days, "project_id": project_id},
        "counts": counts,
        "metrics": {
            "delivery_rate": _ratio(counts["delivered"], terminal, counts["pending"], "人工交付 Run / 已结束 Run（交付、失败、取消）；运行中与等待人工处理另列，不进分母。"),
            "automatic_check_rate": _ratio(sum(checks), len(checks), len(runs) - len(checks), "最后一条自动检查记录明确通过的 Run / 最后一条检查记录结果可识别的 Run；不跳过未知结果回看旧通过记录，独立于人工验收。"),
            "delivery_seconds": _median(delivery_values, counts["delivered"], "已人工交付且有有效 accepted_at 的 Run，从创建到验收的经过秒数中位数，包含人工等待。"),
            "execution_seconds": _median(execution_values, len(runs), "有新版完整计时的 Run 累计执行秒数中位数，含已记录失败和取消执行段，不含人工等待。"),
            "estimated_cost": _metric(round(sum(costs), 8) if costs else None, len(costs), len(runs) - len(costs), f"有可追溯同币种记录的 Run 已记录 token 估算成本之和（{currency}）；Mock 为零；缺失、旧版未定价及异币种记录不补零，非实际账单。"),
            "iteration_fix_rate": _ratio(iteration["fixed"], iteration["comparable"], iteration["pending"] + iteration["excluded"], "父版有失败观察且输入、预期相同的场景中，本版通过数 / 本版已实际复验数；按同来源父子版本对计数，范围改变和未复验不算修复。"),
        },
        "iteration": iteration, "currency": currency,
        "pricing_basis": "分段保存的配置单价 × 模型返回 token；历史无快照不反推，异币种不相加，不含未返回 usage 的调用。",
        "rows": rows, "notes": notes,
    }
