"""运行看门狗：扫描卡死的 run，标记失败，防止一直挂着烧钱。

超时未证明"还活着"默认按异常处理：running 且非等待人工态，
且超过 RUN_STUCK_TIMEOUT 无进度，判定卡死并熔断。
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone

from app.core.config import settings
from app.models import FactoryRun, SessionLocal, init_db
from app.services.stages import Stage

logger = logging.getLogger("factory.watchdog")

# 等待人工确认是正常停留，不判卡死（含待验收）
WAIT_STAGES = {Stage.AWAITING_ANSWERS.value, Stage.AWAITING_PRD_CONFIRM.value, Stage.AWAITING_ACCEPTANCE.value}
# 终态（与 stages.TERMINAL_STAGES 对齐）
TERMINAL = {Stage.DELIVERED.value, Stage.GATE_FAILED.value, Stage.FAILED.value, Stage.CANCELLED.value}


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def check_stuck_runs() -> int:
    """扫描卡死的 run，标记 failed。返回标记数量。"""
    from app.services import engine  # 延迟导入，避免循环

    session = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        runs = session.query(FactoryRun).filter(FactoryRun.status == "running").all()
        marked = 0
        for run in runs:
            if run.current_stage in WAIT_STAGES or run.current_stage in TERMINAL:
                continue
            updated = _as_utc(run.updated_at) or _as_utc(run.created_at)
            if updated is None:
                continue
            elapsed = (now - updated).total_seconds()
            if elapsed > settings.run_stuck_timeout:
                engine._mark_failed(
                    session, run.id, "run_stuck",
                    f"流水线卡死超时（{int(elapsed)}s 无进度），已熔断",
                )
                logger.warning("卡死 run 已熔断 run=%s elapsed=%.0fs", run.id, elapsed)
                marked += 1
        return marked
    finally:
        session.close()


def _loop() -> None:
    while True:
        try:
            check_stuck_runs()
        except Exception:
            logger.exception("看门狗扫描异常")
        time.sleep(settings.watchdog_interval)


def start_watchdog() -> None:
    init_db()
    threading.Thread(target=_loop, daemon=True, name="run-watchdog").start()
    logger.info(
        "看门狗已启动 interval=%ds stuck_timeout=%ds",
        settings.watchdog_interval, settings.run_stuck_timeout,
    )
