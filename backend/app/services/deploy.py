"""部署工序：生成一键部署脚本 + 上线验收清单（确定性代码，不依赖模型）。"""
from __future__ import annotations

from pathlib import Path

DATA_ROOT = Path(__file__).resolve().parents[2] / "data"


def _deploy_dir(run_id: str) -> Path:
    safe = "".join(c for c in run_id if c.isalnum() or c in "-_")
    d = (DATA_ROOT / "code" / safe / "deploy").resolve()
    if not d.is_relative_to(DATA_ROOT.resolve()):
        raise ValueError("非法部署目录")
    d.mkdir(parents=True, exist_ok=True)
    return d


def generate_deploy(run_id: str, idea: str) -> dict[str, str]:
    """生成 start.sh 与上线验收清单，返回文件路径字典。"""
    d = _deploy_dir(run_id)
    start_script = (
        "#!/usr/bin/env bash\n"
        f"# {idea} · 一键启动脚本\n"
        "set -e\n"
        'cd "$(dirname "$0")/.."\n'
        "pip install -r requirements.txt\n"
        "uvicorn app:app --port 8000\n"
    )
    (d / "start.sh").write_text(start_script, encoding="utf-8")
    (d / "start.sh").chmod(0o755)

    checklist = (
        f"# {idea} · 上线验收清单\n\n"
        "产品经理照着点：\n\n"
        "1. 运行 `bash deploy/start.sh`，看到程序输出、不报错；\n"
        "2. （接入真实模型后）把模型 API Key 填到 `.env`；\n"
        "3. 用真实输入完整走一次流程；\n"
        "4. 结果对照 PRD 验收标准（三维打分 ≥2 分）确认达标。\n"
    )
    (d / "上线验收清单.md").write_text(checklist, encoding="utf-8")

    return {
        "start_sh": str(d / "start.sh"),
        "checklist": str(d / "上线验收清单.md"),
    }
