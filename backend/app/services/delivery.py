"""从本轮确定的生成产物构建本地交付包，不遍历用户工作区或运行目录。"""
from __future__ import annotations

import ast
import io
import json
import os
import re
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import AppError
from app.models import Decision, EvidenceItem, FactoryRun, StageEvent
from app.services import iteration
from app.services.stages import Stage
from app.services.version_visibility import visible_parent_ids

DATA_ROOT = Path(__file__).resolve().parents[2] / "data"
DELIVERY_STAGES = {Stage.GATE_PASSED.value, Stage.AWAITING_ACCEPTANCE.value, Stage.DELIVERED.value}
# 与 engine._write_code / deploy.generate_deploy 的输出契约一致；不把运行时文件当成源码。
GENERATED_FILES = (
    "app.py", "requirements.txt", "README.md", "deploy/start.sh", "deploy/上线验收清单.md",
)
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_BUNDLE_BYTES = 12 * 1024 * 1024
MAX_EVIDENCE_FILES = 50
MAX_ENTRIES = 80
EVIDENCE_STAGES = {"prd", "code", "readme", "deploy", "gate", "acceptance"}
_CREDENTIAL_NAME = re.compile(r"api_?key|access_?key|secret|password|token|credential", re.I)
_LITERAL_CREDENTIAL = re.compile(
    r"(?P<prefix>[\"']?(?:[a-z0-9_]*(?:api_?key|access_?key(?:_id|_secret)?|secret(?:_key)?|password|token))[\"']?\s*[:=]\s*)"
    r"(?P<quote>[\"'])(?P<value>[^\"'\r\n]{6,})(?P=quote)", re.I,
)


@dataclass(frozen=True)
class DeliveryBundle:
    filename: str
    content: bytes


def _json_list(raw) -> list:
    if isinstance(raw, list):
        return raw
    try:
        value = json.loads(raw or "[]")
        return value if isinstance(value, list) else []
    except (ValueError, TypeError):
        return []


def _redactor():
    """不读取 .env 文件；移除当前配置中的凭证和常见明文凭证字面量。"""
    values = dict(os.environ)
    values.update(settings.model_dump())
    secrets = sorted(
        {v for k, v in values.items() if _CREDENTIAL_NAME.search(k) and isinstance(v, str) and len(v) >= 4},
        key=len, reverse=True,
    )

    def redact(text: str) -> str:
        for secret in secrets:
            text = text.replace(secret, "[REDACTED]")
        text = _LITERAL_CREDENTIAL.sub(lambda m: m["prefix"] + m["quote"] + "[REDACTED]" + m["quote"], text)
        return re.sub(r"\b(?:sk-[a-zA-Z0-9_-]{12,}|Bearer\s+[a-zA-Z0-9._~-]{12,})", "[REDACTED]", text)

    return redact


def _run_directory(kind: str, run_id: str) -> Path:
    # 不用字符过滤将恶意 ID 映射为另一个 Run 的目录。
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", run_id):
        raise AppError("bundle_path_invalid", "交付产物路径无效", 409)
    root = DATA_ROOT.absolute()
    directory = root / kind / run_id
    if any(p.is_symlink() for p in (root, root / kind, directory)):
        raise AppError("bundle_path_invalid", "交付产物不能使用符号链接", 409)
    if not directory.resolve().is_relative_to(root.resolve()):
        raise AppError("bundle_path_invalid", "交付产物路径无效", 409)
    return directory


def _read_text(path: Path, root: Path) -> tuple[str, int]:
    try:
        relative = path.relative_to(root)
        if not relative.parts or any(part in {"..", "."} for part in relative.parts):
            raise ValueError("invalid relative path")
        if any((root.joinpath(*relative.parts[:i])).is_symlink() for i in range(1, len(relative.parts) + 1)):
            raise ValueError("symlink")
        if not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("outside run")
        file_stat = path.stat()
        if not stat.S_ISREG(file_stat.st_mode):
            raise ValueError("not a regular file")
        if file_stat.st_size > MAX_FILE_BYTES:
            raise AppError("bundle_too_large", "单个交付文件过大，无法打包", 413)
        # 二次限制读取量，避免 stat 后文件增长而分配不受控内存。
        with path.open("rb") as source:
            raw = source.read(MAX_FILE_BYTES + 1)
        if len(raw) > MAX_FILE_BYTES:
            raise AppError("bundle_too_large", "单个交付文件过大，无法打包", 413)
        return raw.decode("utf-8"), file_stat.st_mode
    except AppError:
        raise
    except (OSError, UnicodeError, ValueError) as exc:
        raise AppError("bundle_incomplete", "本轮交付文件缺失或不可安全读取，请重新生成", 409) from exc


def _env_example(source: str) -> str:
    names: set[str] = set()
    try:
        for node in ast.walk(ast.parse(source)):
            value = None
            if isinstance(node, ast.Call) and node.args:
                function = ast.unparse(node.func)
                if function in {"os.getenv", "getenv", "os.environ.get", "environ.get"}:
                    value = node.args[0]
            elif isinstance(node, ast.Subscript) and ast.unparse(node.value) in {"os.environ", "environ"}:
                value = node.slice
            if isinstance(value, ast.Constant) and isinstance(value.value, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", value.value):
                names.add(value.value)
    except (SyntaxError, ValueError, RecursionError):
        pass
    lines = ["# 仅列出生成应用读取的环境变量；不包含真实凭证或工厂配置。", "# 请根据 app/README.md 填写，并按应用说明加载或导出环境变量。"]
    lines += [f"{name}=" for name in sorted(names)]
    if not names:
        lines.append("# 当前代码未发现需要填写的环境变量。")
    return "\n".join(lines) + "\n"


def build_bundle(session: Session, run: FactoryRun) -> DeliveryBundle:
    if run.current_stage not in DELIVERY_STAGES:
        raise AppError("bundle_not_ready", "成品尚未通过本地检查，暂不能下载交付包", 409)
    code_root = _run_directory("code", run.id)
    evidence_root = _run_directory("evidence", run.id)
    redact = _redactor()
    entries: dict[str, tuple[bytes, int]] = {}
    total = 0

    def add(name: str, content: str, mode: int = 0o644) -> None:
        nonlocal total
        raw = redact(content).encode("utf-8")
        total += len(raw)
        if len(raw) > MAX_FILE_BYTES or total > MAX_BUNDLE_BYTES or len(entries) >= MAX_ENTRIES:
            raise AppError("bundle_too_large", "交付包超出大小或文件数量限制", 413)
        entries[name] = (raw, 0o755 if mode & 0o111 else 0o644)

    source = ""
    for name in GENERATED_FILES:
        content, mode = _read_text(code_root / name, code_root)
        if name in {"app.py", "requirements.txt"} and not content.strip():
            raise AppError("bundle_incomplete", "本轮缺少可运行的应用源码或依赖清单", 409)
        add("app/" + name, content, mode)
        if name == "app.py":
            source = content
    add("app/.env.example", _env_example(source))

    items = session.query(EvidenceItem).filter(
        EvidenceItem.run_id == run.id, EvidenceItem.stage.in_(EVIDENCE_STAGES),
    ).order_by(EvidenceItem.id.asc()).limit(MAX_EVIDENCE_FILES + 1).all()
    if len(items) > MAX_EVIDENCE_FILES:
        raise AppError("bundle_too_large", "本轮证据文件过多，无法打包", 413)
    latest_prd = ""
    for item in items:
        content, _ = _read_text(Path(item.content_path), evidence_root)
        add(f"docs/evidence/{item.id}-{item.stage}.md", content)
        if item.stage == "prd":
            latest_prd = content
    if not latest_prd.strip():
        raise AppError("bundle_incomplete", "本轮缺少已生成的 PRD，无法构成完整交付包", 409)
    add("docs/PRD.md", latest_prd)

    decisions = session.query(Decision).filter(Decision.run_id == run.id).order_by(Decision.id.asc()).all()
    ledger = ["# 决策记录", ""]
    for decision in decisions:
        ledger += [f"## {decision.code} · {decision.question}", "", f"状态：{decision.status}",
                   f"是否关键决策：{'是' if decision.is_critical else '否'}", f"备选：{decision.options}",
                   f"推荐：{decision.recommendation}", f"未定影响：{decision.consequence}",
                   f"最终回答：{decision.answer or '尚未回答'}", ""]
    if not decisions:
        ledger.append("本轮没有保存决策记录。")
    feedback = _json_list(getattr(run, "requirement_feedback", None))
    if feedback:
        ledger += ["## 需求修订记录", "", "```json", json.dumps(feedback, ensure_ascii=False, indent=2), "```"]
    add("docs/decisions.md", "\n".join(ledger))

    accepted_at = getattr(run, "accepted_at", None)
    outcome = iteration.acceptance_outcome(run)
    acceptance = {
        "run_id": run.id,
        "stage": run.current_stage,
        "outcome": outcome,
        "mode": getattr(run, "acceptance_mode", None) or "basic",
        "accepted_at": accepted_at.isoformat() if accepted_at else None,
        "note": getattr(run, "acceptance_note", None) or "",
        "scenarios": _json_list(getattr(run, "acceptance_scenarios", None)),
        "results": _json_list(getattr(run, "acceptance_results", None)),
        "checklist": _json_list(getattr(run, "acceptance_checklist", None)),
    }
    add("docs/acceptance.json", json.dumps(acceptance, ensure_ascii=False, indent=2))
    acceptance_lines = ["# 人工验收与真实任务观察", "", f"当前阶段：{run.current_stage}",
                        f"验收模式：{acceptance['mode']}", f"验收时间：{acceptance['accepted_at'] or '未记录'}",
                        f"验收备注：{acceptance['note'] or '未填写'}", ""]
    if outcome == "rejected":
        acceptance_lines += ["主流程验收未通过。本包供本地运行与修改使用，不得标为已交付。", ""]
    elif run.current_stage != Stage.DELIVERED.value:
        acceptance_lines += ["本包供本地运行与验收使用；人工验收尚未通过。", ""]
    if not acceptance["results"]:
        acceptance_lines += ["尚未保存真实任务观察，不能据此宣称真实场景已验证。", ""]
    result_by_id = {str(r.get("scenario_id")): r for r in acceptance["results"] if isinstance(r, dict)}
    for scenario in acceptance["scenarios"]:
        if not isinstance(scenario, dict):
            continue
        result = result_by_id.get(str(scenario.get("id")), {})
        verdict = "通过" if result.get("passed") is True else "未通过" if result.get("passed") is False else "待验证"
        acceptance_lines += [f"## {scenario.get('title', scenario.get('id', '场景'))}", "",
                             f"输入 / 操作：{scenario.get('input', '')}", f"预期结果：{scenario.get('expected_output', '')}",
                             f"结果：{verdict}", f"真实观察：{result.get('observation') or '尚未记录'}", ""]
    for check in acceptance["checklist"]:
        if isinstance(check, dict):
            acceptance_lines.append(f"- [{'x' if check.get('passed') is True else ' '}] {check.get('label') or check.get('id', '')}")
    add("docs/acceptance.md", "\n".join(acceptance_lines))

    test_events = session.query(StageEvent).filter(
        StageEvent.run_id == run.id, StageEvent.event_type == "test_result",
    ).order_by(StageEvent.id.desc()).limit(50).all()
    add("docs/tests.json", json.dumps([
        {"stage": e.stage, "result": e.payload, "created_at": e.created_at.isoformat() if e.created_at else None}
        for e in reversed(test_events)
    ], ensure_ascii=False, indent=2))
    metadata = {
        "run_id": run.id, "idea": run.idea, "stage": run.current_stage,
        "execution_mode": run.execution_mode or "workflow",
        "parent_run_id": visible_parent_ids(session, [getattr(run, "parent_run_id", None)]).get(run.parent_run_id) if getattr(run, "parent_run_id", None) else None,
        "change_request": getattr(run, "change_request", None) or "",
        "llm_provider": run.llm_provider, "llm_model": run.llm_model_snapshot,
    }
    add("docs/run.json", json.dumps(metadata, ensure_ascii=False, indent=2))
    if run.execution_mode == "agent_team":
        from app.services.agent_harness import execution_view
        add("docs/execution.json", json.dumps(execution_view(run), ensure_ascii=False, indent=2))
    status = "人工验收已通过" if outcome == "accepted" else "验收未通过" if outcome == "rejected" else "待人工验收"
    add("README.md", f"""# 本地小应用交付包

需求：{run.idea}

Run：{run.id} · 状态：{status}

## 在本地运行

1. 解压到自己的应用目录，先阅读 `app/README.md` 与 `docs/PRD.md`。
2. 在终端进入解压后的 `app` 目录，准备 Python 3.10 或以上版本。
3. 建议创建独立环境：`python3 -m venv .venv`；macOS / Linux 执行 `source .venv/bin/activate`，Windows 执行 `.venv\\Scripts\\activate`。
4. 按 `app/.env.example` 和应用说明补齐自己的环境变量。模板的值全部为空；有 `os.getenv` 默认值的变量可保留未设置。工厂的模型凭证不会随包交付。
5. macOS / Linux 执行 `bash deploy/start.sh`；Windows 可依次执行 `python -m pip install -r requirements.txt`、`python -m uvicorn app:app --port 8000`。
6. 打开 `http://127.0.0.1:8000`；如应用仅提供接口，打开 `http://127.0.0.1:8000/docs`。

`.env` 不会被所有应用自动加载，请按应用 README 将所需变量导出到当前终端，再启动应用。

## 核对结果

- `docs/PRD.md` 是本轮最新 PRD；历史 PRD 和其他证据在 `docs/evidence/`。
- `docs/decisions.md` 保存决策与需求修订；`docs/run.json` 保存本轮与来源 Run 的关系。
- `docs/acceptance.md` / `.json` 保存验收清单、场景和实际观察；`docs/tests.json` 保存最近 50 次自动检查结果。自动检查不代表人工验收。
- Agent 协作模式额外包含 `docs/execution.json`，可核对角色任务、工具调用和交接摘要；不包含私有模型上下文。
- 待验收包用于运行与核对，须完成真实任务并在工厂提交验收后才算交付。
- 模型来源为 `{run.llm_provider or '未记录'}`；mock 产物只能说明流程可演示，不能代表真实模型效果。
- 应用保留生成时的依赖与启动说明；联网安装依赖、填写第三方服务凭证后才能使用对应能力。

## 文件范围

只包含本轮生成器的五个源码 / 运行文件、脱敏配置模板及本轮产品资料。数据库、日志、缓存、虚拟环境、用户工作区和真实凭证均不在交付包中。检测到的凭证文字以 `[REDACTED]` 替换，需使用者配置自己的值。网页在线托管不属于本包交付范围。
""")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, (content, mode) in entries.items():
            info = zipfile.ZipInfo(name)
            info.create_system = 3
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | mode) << 16
            archive.writestr(info, content)
    suffix = "delivered" if run.current_stage == Stage.DELIVERED.value else "review"
    return DeliveryBundle(filename=f"agent-factory-{run.id}-{suffix}.zip", content=buffer.getvalue())
