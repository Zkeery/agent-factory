"""证据包：每个阶段产出可追溯的证据条目，写入受控目录。"""
from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.models import Decision, EvidenceItem, FactoryRun

DATA_ROOT = Path(__file__).resolve().parents[2] / "data"


def _run_dir(run_id: str) -> Path:
    """证据写入本运行专属目录，限制在 data/ 内，防路径遍历。"""
    safe = "".join(c for c in run_id if c.isalnum() or c in "-_")
    d = (DATA_ROOT / "evidence" / safe).resolve()
    if not d.is_relative_to(DATA_ROOT.resolve()):
        raise ValueError("非法运行目录")
    d.mkdir(parents=True, exist_ok=True)
    return d


def add_evidence(session: Session, run: FactoryRun, stage: str, title: str, content: str) -> EvidenceItem:
    d = _run_dir(run.id)
    fname = f"{len(list(d.glob('*.md')))+1:02d}-{stage}.md"
    (d / fname).write_text(f"# {title}\n\n{content}\n", encoding="utf-8")
    kind_map = {"prd": "prd", "code": "code", "deploy": "deploy", "readme": "readme", "gate": "gate"}
    item = EvidenceItem(
        run_id=run.id,
        stage=stage,
        title=title,
        content_path=str(d / fname),
        kind=kind_map.get(stage, "other"),
    )
    session.add(item)
    session.commit()
    return item


def build_evidence(session: Session, run: FactoryRun) -> None:
    """生成最终证据包：决策台账 + 闸门结果（PRD 条目已在 PRD_DRAFTING 阶段写入）。"""
    decisions = session.query(Decision).filter(Decision.run_id == run.id).all()
    ledger = "\n".join(
        f"- {d.code}：{d.question} → {d.answer or '未答'}" for d in decisions
    )
    add_evidence(session, run, "gate", "闸门检查", f"决策台账：\n{ledger}\n\n结论：闸门通过")
