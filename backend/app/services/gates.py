"""闸门检查：确定性代码判断各阶段是否满足通过条件，不交给模型。"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Confirmation, Decision, EvidenceItem, FactoryRun, StageEvent


def all_decisions_answered(session: Session, run: FactoryRun) -> bool:
    decisions = session.query(Decision).filter(Decision.run_id == run.id).all()
    return len(decisions) > 0 and all(d.status == "answered" for d in decisions)


def prd_confirmed(session: Session, run: FactoryRun) -> bool:
    c = (
        session.query(Confirmation)
        .filter(Confirmation.run_id == run.id, Confirmation.kind == "prd")
        .first()
    )
    return c is not None and c.status == "confirmed"


def build_artifacts_ready(session: Session, run: FactoryRun) -> bool:
    """构建闸门：测试通过 + 部署产物已生成。"""
    # 取最新一条：就地重测会追加新的 test_result，不能用最早的失败记录误判闸门
    ev = (
        session.query(StageEvent)
        .filter(StageEvent.run_id == run.id, StageEvent.event_type == "test_result")
        .order_by(StageEvent.id.desc())
        .first()
    )
    test_passed = ev is not None and ev.payload == "passed"
    deploy_item = (
        session.query(EvidenceItem)
        .filter(EvidenceItem.run_id == run.id, EvidenceItem.stage == "deploy")
        .first()
    )
    return test_passed and deploy_item is not None


def evidence_ready(session: Session, run: FactoryRun) -> bool:
    items = session.query(EvidenceItem).filter(EvidenceItem.run_id == run.id).all()
    return len(items) > 0


def final_gate(session: Session, run: FactoryRun) -> bool:
    """最终闸门：澄清、PRD、构建、证据四道子闸门全部通过。"""
    return (
        all_decisions_answered(session, run)
        and prd_confirmed(session, run)
        and build_artifacts_ready(session, run)
        and evidence_ready(session, run)
    )


def acceptance_confirmed(session: Session, run: FactoryRun) -> bool:
    c = (
        session.query(Confirmation)
        .filter(Confirmation.run_id == run.id, Confirmation.kind == "acceptance")
        .first()
    )
    return c is not None and c.status == "confirmed"
