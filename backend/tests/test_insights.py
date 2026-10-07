"""复盘口径与隐私：分母、时间边界、模型来源和可比的迭代样本。"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.models import FactoryRun, ProductProject, RunMetric, StageEvent, User
from app.schemas.insights import ReviewOut
from app.services import insights, metrics

NOW = datetime(2026, 10, 5, 12, tzinfo=timezone.utc)


def _run(session, id, *, stage="delivered", source="real", owner="owner", created_at=None, **kwargs):
    provider, model = {"real": ("deepseek", "deepseek-chat"), "mock": ("mock", "mock"), "unknown": ("", "")}[source]
    run = FactoryRun(id=id, idea=f"需求 {id}", user_id=owner, current_stage=stage,
                     status="done" if stage in {"delivered", "failed", "gate_failed", "cancelled"} else "running",
                     llm_provider=provider, llm_model_snapshot=model,
                     created_at=created_at or NOW - timedelta(days=1), **kwargs)
    session.add(run)
    session.commit()
    return run


def _metric(session, run, *, seconds=10.0, cost=0.5, currency="USD", legacy=False):
    snapshot = {"kind": "segment", "version": 1, "source": metrics.run_source(run), "currency": currency,
                "input_per_million": 1.0, "output_per_million": 2.0, "estimated_cost": cost,
                "duration_seconds": seconds, "outcome": "completed"}
    record = RunMetric(run_id=run.id, duration_seconds=seconds, cost_estimate=cost,
                       accounting_version=0 if legacy else 1, recorded_segments=0 if legacy else 1,
                       pricing_snapshots="[]" if legacy else json.dumps([snapshot]))
    session.add(record)
    session.commit()
    return record


def _review(session, **kwargs):
    value = insights.build_review(session, "owner", now=NOW, **kwargs)
    ReviewOut.model_validate(value)
    return value


@pytest.fixture(autouse=True)
def fixed_currency(monkeypatch):
    monkeypatch.setattr(metrics.settings, "cost_currency", "USD")


def test_empty_review_is_null_not_zero_success(session):
    value = _review(session)
    assert value["counts"]["total"] == 0
    assert all(metric["value"] is None and metric["samples"] == 0 for metric in value["metrics"].values())
    assert value["rows"] == []
    assert value["filters"] == {"source": "real", "days": "all", "project_id": None}
    assert set(value["metrics"]) == {"delivery_rate", "automatic_check_rate", "delivery_seconds", "execution_seconds", "estimated_cost", "iteration_fix_rate"}


def test_terminal_denominator_includes_cancel_but_not_pending(session):
    stages = ["delivered", "delivered", "failed", "gate_failed", "cancelled", "awaiting_acceptance"]
    for index, stage in enumerate(stages):
        _run(session, f"r{index}", stage=stage)
    value = _review(session)
    assert value["counts"] == {"total": 6, "delivered": 2, "failed": 2, "cancelled": 1, "pending": 1, "real": 6, "mock": 0, "unknown": 0}
    metric = value["metrics"]["delivery_rate"]
    assert (metric["value"], metric["numerator"], metric["denominator"], metric["excluded"]) == (0.4, 2, 5, 1)


def test_automatic_checks_use_latest_result_and_do_not_infer_human_acceptance(session):
    first = _run(session, "first", stage="awaiting_acceptance")
    second = _run(session, "second", stage="gate_failed")
    missing = _run(session, "no-result")
    for run, payload in [(first, "failed: first check"), (first, "passed"),
                         (second, "passed"), (second, json.dumps({"passed": False})),
                         (missing, "passed"), (missing, json.dumps({"status": ["passed"]}))]:
        session.add(StageEvent(run_id=run.id, stage="testing", event_type="test_result", payload=payload,
                               created_at=NOW - timedelta(minutes=1)))
    session.commit()
    value = _review(session)
    check = value["metrics"]["automatic_check_rate"]
    assert (check["numerator"], check["denominator"], check["value"], check["excluded"]) == (1, 2, 0.5, 1)
    assert value["counts"]["pending"] == 1
    assert value["counts"]["delivered"] == 1


def test_delivery_and_execution_medians_have_distinct_samples(session):
    first = _run(session, "first", accepted_at=NOW - timedelta(days=1) + timedelta(seconds=120))
    second = _run(session, "second", accepted_at=NOW - timedelta(days=1) + timedelta(seconds=360))
    legacy = _run(session, "legacy")
    _metric(session, first, seconds=10)
    _metric(session, second, seconds=30)
    _metric(session, legacy, seconds=999, cost=500, legacy=True)
    value = _review(session)
    assert value["metrics"]["delivery_seconds"]["value"] == 240
    assert value["metrics"]["delivery_seconds"]["samples"] == 2
    assert value["metrics"]["delivery_seconds"]["excluded"] == 1
    assert value["metrics"]["execution_seconds"]["value"] == 20
    assert value["metrics"]["execution_seconds"]["excluded"] == 1
    assert value["metrics"]["estimated_cost"]["value"] == 1
    assert next(row for row in value["rows"] if row["run_id"] == "legacy")["estimated_cost"] is None


def test_invalid_acceptance_time_does_not_create_negative_or_future_delivery_duration(session):
    _run(session, "negative", accepted_at=NOW - timedelta(days=2))
    _run(session, "future", accepted_at=NOW + timedelta(seconds=1))
    value = _review(session)
    assert value["metrics"]["delivery_seconds"]["value"] is None
    assert value["metrics"]["delivery_seconds"]["excluded"] == 2


def test_interrupted_accounting_excludes_cost_and_execution_but_keeps_delivery_duration(session):
    interrupted = _run(session, "interrupted", accepted_at=NOW - timedelta(days=1) + timedelta(seconds=120),
                       execution_state=json.dumps({"accounting_incomplete": True}))
    complete = _run(session, "complete", accepted_at=NOW - timedelta(days=1) + timedelta(seconds=360))
    _metric(session, interrupted, seconds=10, cost=100)
    _metric(session, complete, seconds=30, cost=0.5)

    value = _review(session)
    row = next(row for row in value["rows"] if row["run_id"] == interrupted.id)
    assert row["execution_seconds"] is None
    assert row["estimated_cost"] is None
    assert row["delivery_seconds"] == 120
    for key, expected in (("execution_seconds", 30), ("estimated_cost", 0.5)):
        metric = value["metrics"][key]
        assert (metric["value"], metric["samples"], metric["excluded"]) == (expected, 1, 1)
    delivery = value["metrics"]["delivery_seconds"]
    assert (delivery["value"], delivery["samples"], delivery["excluded"]) == (240, 2, 0)
    assert any("曾异常中断" in note for note in value["notes"])


def test_time_window_includes_exact_boundaries_and_excludes_future_runs(session):
    _run(session, "start", created_at=NOW - timedelta(days=7))
    _run(session, "before", created_at=NOW - timedelta(days=7, microseconds=1))
    _run(session, "end", created_at=NOW)
    _run(session, "future", created_at=NOW + timedelta(microseconds=1))
    assert {row["run_id"] for row in _review(session, days="7")["rows"]} == {"start", "end"}
    assert {row["run_id"] for row in _review(session, days="all")["rows"]} == {"start", "end", "before"}


def test_real_mock_unknown_and_all_filters_do_not_mix_samples(session):
    for source in ("real", "mock", "unknown"):
        _run(session, source, source=source)
    for source in ("real", "mock", "unknown"):
        value = _review(session, source=source)
        assert value["counts"]["total"] == 1
        assert value["rows"][0]["source"] == source
    assert _review(session, source="all")["counts"]["total"] == 3
    assert any("混合来源" in note for note in _review(session, source="all")["notes"])


def test_missing_duplicate_and_different_currency_metrics_are_not_filled_with_zero(session):
    missing = _run(session, "missing")
    duplicate = _run(session, "duplicate")
    foreign_currency = _run(session, "different-currency")
    _metric(session, duplicate)
    _metric(session, duplicate)
    _metric(session, foreign_currency, currency="CNY")
    value = _review(session)
    assert value["metrics"]["estimated_cost"]["value"] is None
    assert value["metrics"]["estimated_cost"]["excluded"] == 3
    assert next(row for row in value["rows"] if row["run_id"] == missing.id)["execution_seconds"] is None
    assert any("多条累计度量" in note for note in value["notes"])


def _scenario(id, value, expected):
    return {"id": id, "title": id, "input": value, "expected_output": expected}


def _result(id, passed, observation="实际观察"):
    return {"scenario_id": id, "passed": passed, "observation": observation}


def _revision_pair(session, *, parent_source="real"):
    baseline = [_scenario("old-a", "输入一", "结果一"), _scenario("same-id", "输入二", "结果二"),
                _scenario("pending", "输入三", "结果三"), _scenario("stable", "输入四", "结果四")]
    observations = [_result("old-a", False), _result("same-id", False), _result("pending", False), _result("stable", True)]
    parent = _run(session, "parent", source=parent_source, created_at=NOW - timedelta(days=40))
    child = _run(session, "child", parent_run_id=parent.id, acceptance_mode="scenario",
                 parent_context=json.dumps({"acceptance_scenarios": baseline, "acceptance_results": observations}, ensure_ascii=False),
                 acceptance_scenarios=json.dumps([
                     _scenario("new-a", "输入一", "结果一"), _scenario("same-id", "改变后的输入", "新的预期"),
                     _scenario("pending", "输入三", "结果三"), _scenario("stable", "输入四", "结果四"),
                     _scenario("new-task", "新增输入", "新增结果"),
                 ], ensure_ascii=False),
                 acceptance_results=json.dumps([_result("new-a", True), _result("same-id", True),
                                                _result("pending", False, ""), _result("stable", False), _result("new-task", False)], ensure_ascii=False))
    return parent, child


def test_iteration_matches_inputs_and_expected_results_not_ids(session):
    _revision_pair(session)
    value = _review(session, days="7")  # 父版在窗口外，仍读取创建子版时的基线。
    assert value["counts"]["total"] == 1
    assert value["iteration"] == {"baseline_failed": 3, "comparable": 1, "fixed": 1, "pending": 1, "excluded": 1, "new_failures": 2}
    assert value["metrics"]["iteration_fix_rate"]["value"] == 1.0
    assert value["metrics"]["iteration_fix_rate"]["denominator"] == 1
    assert value["metrics"]["iteration_fix_rate"]["excluded"] == 2


def test_iteration_does_not_claim_real_improvement_over_mock_baseline(session):
    _revision_pair(session, parent_source="mock")
    value = _review(session, days="7")
    assert value["iteration"]["baseline_failed"] == 3
    assert value["iteration"]["excluded"] == 3
    assert value["iteration"]["fixed"] == value["iteration"]["new_failures"] == 0
    assert value["metrics"]["iteration_fix_rate"]["value"] is None


def test_iteration_missing_baseline_is_null(session):
    parent = _run(session, "parent")
    _run(session, "child", parent_run_id=parent.id, parent_context="{}")
    value = _review(session)
    assert value["metrics"]["iteration_fix_rate"]["value"] is None
    assert any("缺少父快照" in note for note in value["notes"])


def test_ambiguous_duplicate_task_fingerprints_are_excluded(session):
    parent = _run(session, "parent")
    baseline = [_scenario("a", "same", "same"), _scenario("b", "same", "same")]
    _run(session, "child", parent_run_id=parent.id,
         parent_context=json.dumps({"acceptance_scenarios": baseline, "acceptance_results": [_result("a", False), _result("b", False)]}),
         acceptance_scenarios=json.dumps([_scenario("c", "same", "same")]),
         acceptance_results=json.dumps([_result("c", True)]))
    value = _review(session)
    assert value["iteration"]["baseline_failed"] == 2
    assert value["iteration"]["excluded"] == 2
    assert value["metrics"]["iteration_fix_rate"]["value"] is None


def test_review_api_is_authenticated_and_owner_scoped_even_for_all(client, session):
    owner = session.query(User).filter(User.phone == "13800138000").one()
    session.add_all([ProductProject(id="own-project", user_id=owner.id, name="我的项目"),
                     ProductProject(id="other-project", user_id="other-user", name="他人项目")])
    session.commit()
    created = datetime.now(timezone.utc) - timedelta(minutes=10)
    _run(session, "mine", owner=owner.id, project_id="own-project", created_at=created)
    _run(session, "theirs", owner="other-user", project_id="other-project", created_at=created)
    assert client.get("/api/v1/metrics/review", headers={"Authorization": ""}).status_code == 401
    response = client.get("/api/v1/metrics/review?source=all")
    assert response.status_code == 200
    body = response.json()
    assert body["counts"]["total"] == 1
    assert [row["run_id"] for row in body["rows"]] == ["mine"]
    assert client.get("/api/v1/metrics/review?source=all&project_id=own-project").json()["counts"]["total"] == 1
    blocked = client.get("/api/v1/metrics/review?source=all&project_id=other-project")
    assert blocked.status_code == 404
    assert blocked.json()["error"]["code"] == "project_not_found"
    assert client.get("/api/v1/metrics/review?project_id=missing").status_code == 404


@pytest.mark.parametrize("query", ["source=imaginary", "days=8", "days=-7"])
def test_invalid_review_filters_use_standard_error_body(client, query):
    response = client.get("/api/v1/metrics/review?" + query)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_review_filter"
