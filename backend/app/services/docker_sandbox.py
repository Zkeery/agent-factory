"""可选 Docker 沙箱：无网、内存限制、只读挂载生成代码。

本机无 Docker 或镜像缺失时由调用方回退到进程沙箱。
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from app.core.config import settings
from app.services.sandbox import format_sandbox_import_error

logger = logging.getLogger("factory.docker_sandbox")


def docker_cli_available() -> bool:
    return shutil.which("docker") is not None


def docker_image_present(image: str | None = None) -> bool:
    if not docker_cli_available():
        return False
    img = image or settings.sandbox_docker_image
    try:
        proc = subprocess.run(
            ["docker", "image", "inspect", img],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return proc.returncode == 0
    except Exception:
        return False


def docker_sandbox_ready() -> bool:
    return docker_cli_available() and docker_image_present()


def run_smoke_import_docker(code_dir: Path) -> tuple[bool, str]:
    """在容器中 import app。成功返回 (True, msg)。"""
    code_dir = code_dir.resolve()
    if not (code_dir / "app.py").is_file():
        return False, "app.py 不存在"

    image = settings.sandbox_docker_image
    timeout = max(1, int(settings.sandbox_timeout_seconds))
    mem_mb = int(settings.sandbox_memory_mb or 0)
    network = (settings.sandbox_docker_network or "none").strip() or "none"

    cmd = [
        "docker",
        "run",
        "--rm",
        "--network",
        network,
        "--read-only",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=64m",
        "--pids-limit",
        "64",
        "--user",
        "65534:65534",  # nobody
        "-v",
        f"{code_dir}:/work/code:ro",
        "-w",
        "/work",
    ]
    if mem_mb > 0:
        cmd.extend(["--memory", f"{mem_mb}m", "--memory-swap", f"{mem_mb}m"])
    # CPU 软限制，避免占满宿主机
    cmd.extend(["--cpus", "0.5"])
    cmd.extend(
        [
            image,
            "python",
            "-I",
            "-c",
            "import sys; sys.path.insert(0, '/work/code'); import app; print('sandbox_ok')",
        ]
    )

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout + 5,  # 拉起容器略留余量
        )
    except subprocess.TimeoutExpired:
        return False, f"Docker 沙箱超时（>{timeout}s）"
    except FileNotFoundError:
        return False, "未找到 docker 命令"
    except Exception as exc:
        return False, f"Docker 沙箱启动失败: {exc}"

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        logger.info("docker sandbox fail rc=%s err=%s", proc.returncode, err[:200])
        return False, format_sandbox_import_error(err, prefix="Docker 沙箱导入失败")
    if "sandbox_ok" not in (proc.stdout or ""):
        return False, "Docker 沙箱未确认成功输出"
    return True, "Docker 沙箱语法与导入检查通过"
