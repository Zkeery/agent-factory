"""度量账本：累计 usage 去重、失败覆盖、段级价格与来源。"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.models import FactoryRun, RunMetric
from app.services import metrics
from app.services.insights import build_review
from app.services.llm import MockLLM


def _run(session, provider="deepseek", model="deepseek-chat"):
    run = FactoryRun(id="accounting-run", idea="一个小应用", user_id="owner", llm_provider=provider,
                     llm_model_snapshot=model, current_stage="failed", status="done")
    session.add(run)
    session.commit()
    return run


@pytest.fixture(autouse=True)
def fixed_pricing(monkeypatch):
    monkeypatch.setattr(metrics.settings, "cost_per_1m_input", 1.0)
    monkeypatch.setattr(metrics.settings, "cost_per_1m_output", 2.0)
    monkeypatch.setattr(metrics.settings, "cost_currency", "USD")


def test_token_deltas_use_each_segments_price_and_keep_old_estimate(session, monkeypatch):
    run = _run(session)
    client = SimpleNamespace(prompt_tokens=1_000_000, completion_tokens=0)
    monkeypatch.setattr(metrics.time, "monotonic", lambda: 110.0)
    record = metrics.record_metric(session, run, client, 100.0)
    assert record.cost_estimate == 1.0
    monkeypatch.setattr(metrics.settings, "cost_per_1m_input", 3.0)
    monkeypatch.setattr(metrics.settings, "cost_per_1m_output", 4.0)
    client.prompt_tokens = 1_500_000
    client.completion_tokens = 200_000
    monkeypatch.setattr(metrics.time, "monotonic", lambda: 135.0)
    record = metrics.record_metric(session, run, client, 120.0, outcome="failed")
    assert record.cost_estimate == pytest.approx(3.3)
    assert record.prompt_tokens == 1_500_000
    assert record.completion_tokens == 200_000
    assert record.duration_seconds == 25.0
    assert record.accounting_version == 1
    assert record.recorded_segments == 2
    assert record.failed_segments == 1
    snapshots = json.loads(record.pricing_snapshots)
    assert [item["input_per_million"] for item in snapshots] == [1.0, 3.0]
    assert [item["estimated_cost"] for item in snapshots] == [1.0, 2.3]
    assert [item["outcome"] for item in snapshots] == ["completed", "failed"]
    review = build_review(session, "owner")
    assert review["metrics"]["estimated_cost"]["value"] == pytest.approx(3.3)


def test_recording_same_client_segment_twice_is_idempotent(session, monkeypatch):
    run = _run(session)
    client = SimpleNamespace(prompt_tokens=100, completion_tokens=20)
    monkeypatch.setattr(metrics.time, "monotonic", lambda: 20.0)
    first = metrics.record_metric(session, run, client, 10.0)
    original = (first.duration_seconds, first.cost_estimate, first.pricing_snapshots)
    metrics.record_metric(session, run, client, 10.0)
    assert first.recorded_segments == 1
    assert (first.duration_seconds, first.cost_estimate, first.pricing_snapshots) == original
    assert session.query(RunMetric).filter(RunMetric.run_id == run.id).count() == 1


def test_new_client_records_its_own_tokens_and_cancelled_duration(session, monkeypatch):
    run = _run(session)
    monkeypatch.setattr(metrics.time, "monotonic", lambda: 10.0)
    record = metrics.record_metric(session, run, SimpleNamespace(prompt_tokens=100, completion_tokens=0), 5.0)
    metrics.record_metric(session, run, SimpleNamespace(prompt_tokens=40, completion_tokens=0), 5.0, outcome="cancelled")
    assert record.prompt_tokens == 140
    assert record.duration_seconds == 10.0
    assert record.recorded_segments == 2
    assert record.failed_segments == 0
    assert json.loads(record.pricing_snapshots)[-1]["outcome"] == "cancelled"


def test_mock_client_has_zero_cost_even_when_run_metadata_is_stale(session, monkeypatch):
    run = _run(session)  # 元数据与实际客户端冲突时，以本段实际客户端为准。
    client = MockLLM()
    client.prompt_tokens = 1_000_000
    monkeypatch.setattr(metrics.time, "monotonic", lambda: 12.0)
    record = metrics.record_metric(session, run, client, 10.0)
    assert record.cost_estimate == 0
    assert metrics.run_source(run, record) == "mock"
    review = build_review(session, "owner", source="mock")
    assert review["counts"]["mock"] == 1
    assert review["metrics"]["estimated_cost"]["value"] == 0


def test_unknown_source_does_not_receive_real_price(session, monkeypatch):
    run = _run(session, provider="", model="")
    monkeypatch.setattr(metrics.time, "monotonic", lambda: 12.0)
    record = metrics.record_metric(session, run, SimpleNamespace(prompt_tokens=1_000_000, completion_tokens=10), 10.0)
    assert metrics.run_source(run, record) == "unknown"
    assert json.loads(record.pricing_snapshots)[0]["estimated_cost"] is None
    review = build_review(session, "owner", source="unknown")
    assert review["metrics"]["estimated_cost"]["value"] is None
    assert review["rows"][0]["estimated_cost"] is None


def test_failed_initialization_without_client_still_records_execution(session, monkeypatch):
    run = _run(session, provider="", model="")
    monkeypatch.setattr(metrics.time, "monotonic", lambda: 6.0)
    record = metrics.record_metric(session, run, None, 5.0, outcome="failed")
    assert record.duration_seconds == 1.0
    assert record.failed_segments == 1
    assert record.prompt_tokens == record.completion_tokens == 0
    assert json.loads(record.pricing_snapshots)[0]["source"] == "unknown"


def test_legacy_values_are_preserved_and_not_repriced(session, monkeypatch):
    run = _run(session)
    record = RunMetric(run_id=run.id, duration_seconds=60.0, prompt_tokens=2_000_000,
                       completion_tokens=0, cost_estimate=12.0)
    session.add(record)
    session.commit()
    monkeypatch.setattr(metrics.time, "monotonic", lambda: 11.0)
    metrics.record_metric(session, run, SimpleNamespace(prompt_tokens=1_000_000, completion_tokens=0), 10.0)
    snapshots = json.loads(record.pricing_snapshots)
    assert snapshots[0]["kind"] == "legacy"
    assert snapshots[0]["estimated_cost"] == 12.0
    assert snapshots[0]["currency"] is None
    assert snapshots[0]["input_per_million"] is None
    assert record.cost_estimate == 13.0  # 保留旧累计栏，review 不把它当成可比较的新账本。
    review = build_review(session, "owner")
    assert review["rows"][0]["execution_seconds"] is None
    assert review["rows"][0]["estimated_cost"] is None
    assert review["metrics"]["estimated_cost"]["samples"] == 0


def test_mixed_currency_does_not_get_summed_in_review(session, monkeypatch):
    run = _run(session)
    monkeypatch.setattr(metrics.time, "monotonic", lambda: 10.0)
    metrics.record_metric(session, run, SimpleNamespace(prompt_tokens=1_000_000, completion_tokens=0), 9.0)
    monkeypatch.setattr(metrics.settings, "cost_currency", "CNY")
    metrics.record_metric(session, run, SimpleNamespace(prompt_tokens=1_000_000, completion_tokens=0), 9.0)
    review = build_review(session, "owner")
    assert review["currency"] == "CNY"
    assert review["metrics"]["estimated_cost"]["value"] is None
    assert review["metrics"]["estimated_cost"]["excluded"] == 1


def test_mixed_mock_and_real_execution_is_unknown(session, monkeypatch):
    run = _run(session)
    monkeypatch.setattr(metrics.time, "monotonic", lambda: 10.0)
    record = metrics.record_metric(session, run, SimpleNamespace(prompt_tokens=100, completion_tokens=0), 9.0)
    metrics.record_metric(session, run, MockLLM(), 9.0)
    assert metrics.run_source(run, record) == "unknown"
    assert build_review(session, "owner", source="real")["counts"]["total"] == 0


def test_invalid_unit_price_is_missing_not_free(session, monkeypatch):
    run = _run(session)
    monkeypatch.setattr(metrics.settings, "cost_per_1m_input", -1.0)
    monkeypatch.setattr(metrics.time, "monotonic", lambda: 10.0)
    record = metrics.record_metric(session, run, SimpleNamespace(prompt_tokens=1_000_000, completion_tokens=0), 9.0)
    assert json.loads(record.pricing_snapshots)[0]["estimated_cost"] is None
    assert build_review(session, "owner")["metrics"]["estimated_cost"]["value"] is None
