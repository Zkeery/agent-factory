"""流水线阶段状态机：固定工序的合法阶段与流转规则。"""
from __future__ import annotations

from enum import Enum


class Stage(str, Enum):
    IDEA_SUBMITTED = "idea_submitted"
    CLARIFYING = "clarifying"
    AWAITING_ANSWERS = "awaiting_answers"
    PRD_DRAFTING = "prd_drafting"
    AWAITING_PRD_CONFIRM = "awaiting_prd_confirm"
    BUILDING = "building"
    TESTING = "testing"
    DEPLOYING = "deploying"
    EVIDENCE_READY = "evidence_ready"
    GATE_PASSED = "gate_passed"  # 自动闸门通过（非交付终态）
    AWAITING_ACCEPTANCE = "awaiting_acceptance"  # 等人验收
    DELIVERED = "delivered"  # 人验收通过
    GATE_FAILED = "gate_failed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# 固定工序：确定性流转，不允许模型自主跳转。
NEXT_STAGE: dict[Stage, Stage] = {
    Stage.IDEA_SUBMITTED: Stage.CLARIFYING,
    Stage.CLARIFYING: Stage.AWAITING_ANSWERS,
    Stage.AWAITING_ANSWERS: Stage.PRD_DRAFTING,
    Stage.PRD_DRAFTING: Stage.AWAITING_PRD_CONFIRM,
    Stage.AWAITING_PRD_CONFIRM: Stage.BUILDING,
    Stage.BUILDING: Stage.TESTING,
    Stage.TESTING: Stage.DEPLOYING,
    Stage.DEPLOYING: Stage.EVIDENCE_READY,
    Stage.EVIDENCE_READY: Stage.GATE_PASSED,
    Stage.GATE_PASSED: Stage.AWAITING_ACCEPTANCE,
    Stage.AWAITING_ACCEPTANCE: Stage.DELIVERED,
}

# 人工等待点：这些阶段必须等产品经理操作后才继续。
WAIT_STAGES: set[Stage] = {
    Stage.AWAITING_ANSWERS,
    Stage.AWAITING_PRD_CONFIRM,
    Stage.AWAITING_ACCEPTANCE,
}

# 终态。
TERMINAL_STAGES: set[Stage] = {
    Stage.DELIVERED,
    Stage.GATE_FAILED,
    Stage.FAILED,
    Stage.CANCELLED,
}
