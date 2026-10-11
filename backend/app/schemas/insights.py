"""项目复盘响应：每个数字同时返回样本、分母与口径。"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SourceFilter = Literal["real", "mock", "unknown", "all"]
ReviewDays = Literal["7", "30", "90", "all"]
RunSource = Literal["real", "mock", "unknown"]


class ReviewMetric(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    value: float | None
    numerator: float | None
    denominator: float | None
    samples: int = Field(ge=0)
    excluded: int = Field(ge=0)
    definition: str


class ReviewFilters(BaseModel):
    source: SourceFilter
    days: ReviewDays
    project_id: str | None


class ReviewCounts(BaseModel):
    total: int
    delivered: int
    failed: int
    cancelled: int
    pending: int
    real: int
    mock: int
    unknown: int


class ReviewMetrics(BaseModel):
    delivery_rate: ReviewMetric
    automatic_check_rate: ReviewMetric
    delivery_seconds: ReviewMetric
    execution_seconds: ReviewMetric
    estimated_cost: ReviewMetric
    iteration_fix_rate: ReviewMetric


class IterationReview(BaseModel):
    baseline_failed: int
    comparable: int
    fixed: int
    pending: int
    excluded: int
    new_failures: int


class ReviewRunRow(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    run_id: str
    project_id: str | None
    idea: str
    stage: str
    source: RunSource
    execution_mode: str
    created_at: datetime
    accepted_at: datetime | None
    delivery_seconds: float | None
    execution_seconds: float | None
    estimated_cost: float | None
    accounting_version: int
    parent_run_id: str | None
    acceptance_outcome: Literal["pending", "rejected", "accepted"] | None = None
    revision_created: bool = False


class ReviewOut(BaseModel):
    generated_at: datetime
    filters: ReviewFilters
    counts: ReviewCounts
    metrics: ReviewMetrics
    iteration: IterationReview
    currency: str
    pricing_basis: str
    rows: list[ReviewRunRow]
    notes: list[str]
