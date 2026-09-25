"""生成代码沙箱：静态危险检查 + 受限子进程 smoke import。

说明：这不是 Docker 级隔离。目标是挡住常见恶意/误操作模式
（危险导入、系统调用、无限循环、过大内存），并避免把宿主机密钥灌进子进程。
"""
from __future__ import annotations

import ast
import os
import signal
import subprocess
import sys
import textwrap
from pathlib import Path

from app.core.config import settings

# 直接 import 即视为高风险（网络、进程、本地提权相关）
BLOCKED_MODULES = frozenset(
    {
        "subprocess",
        "socket",
        "ctypes",
        "multiprocessing",
        "threading",
        "signal",
        "pty",
        "fcntl",
        "resource",
        "pickle",
        "marshal",
        "http.client",
        "http.server",
        "urllib",
        "urllib.request",
        "urllib.error",
        "requests",
        "aiohttp",
        "paramiko",
        "shutil",
        "tempfile",
        "pathlib",
        "importlib",
        "runpy",
        "code",
        "codeop",
        "builtins",
    }
)

# os / sys 上禁止的属性（允许 os.getenv / os.environ）
BLOCKED_ATTRS = frozenset(
    {
        ("os", "system"),
        ("os", "popen"),
        ("os", "execv"),
        ("os", "execve"),
        ("os", "execvp"),
        ("os", "execvpe"),
        ("os", "execl"),
        ("os", "execle"),
        ("os", "execlp"),
        ("os", "execlpe"),
        ("os", "spawnl"),
        ("os", "spawnle"),
        ("os", "spawnlp"),
        ("os", "spawnlpe"),
        ("os", "spawnv"),
        ("os", "spawnve"),
        ("os", "spawnvp"),
        ("os", "spawnvpe"),
        ("os", "fork"),
        ("os", "forkpty"),
        ("os", "kill"),
        ("os", "killpg"),
        ("os", "remove"),
        ("os", "unlink"),
        ("os", "rmdir"),
        ("os", "removedirs"),
        ("os", "rename"),
        ("os", "replace"),
        ("os", "chmod"),
        ("os", "chown"),
        ("os", "symlink"),
        ("os", "link"),
        ("os", "truncate"),
        ("os", "ftruncate"),
        ("sys", "exit"),
        ("sys", "modules"),
    }
)

BLOCKED_CALLS = frozenset({"eval", "exec", "compile", "__import__", "breakpoint", "input"})


class SandboxViolation(Exception):
    """静态检查未通过。"""


def _module_root(name: str) -> str:
    return name.split(".", 1)[0]


def check_source(source: str, *, filename: str = "app.py") -> None:
    """AST 静态检查；不通过则抛 SandboxViolation。"""
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as exc:
        raise SandboxViolation(f"语法错误: {exc}") from exc

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = _module_root(alias.name)
                if alias.name in BLOCKED_MODULES or root in BLOCKED_MODULES:
                    raise SandboxViolation(f"禁止导入: {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                full = node.module
                root = _module_root(full)
                if full in BLOCKED_MODULES or root in BLOCKED_MODULES:
                    raise SandboxViolation(f"禁止导入: {full}")
                if root == "os":
                    for alias in node.names:
                        if (root, alias.name) in BLOCKED_ATTRS:
                            raise SandboxViolation(f"禁止使用: os.{alias.name}")
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in BLOCKED_CALLS:
                raise SandboxViolation(f"禁止调用: {node.func.id}")
            if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                pair = (node.func.value.id, node.func.attr)
                if pair in BLOCKED_ATTRS:
                    raise SandboxViolation(f"禁止调用: {pair[0]}.{pair[1]}")
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            pair = (node.value.id, node.attr)
            if pair in BLOCKED_ATTRS:
                raise SandboxViolation(f"禁止访问: {pair[0]}.{pair[1]}")


_RUNNER = textwrap.dedent(
    r"""
    import builtins
    import os
    import sys

    # 运行时不整模块 ban subprocess/socket：FastAPI/asyncio 会间接导入。
    # 用户源码里的危险 import 由 AST 拦截；这里只打掉可执行出口。
    BLOCKED = {
        "pty", "fcntl", "resource",
        "requests", "aiohttp", "paramiko",
        "runpy", "code", "codeop",
    }

    _real_import = builtins.__import__

    def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):
        # level>0 是包内相对导入（如 fastapi 的 .requests），不能按顶层名误杀
        if level == 0:
            root = name.split(".", 1)[0]
            if name in BLOCKED or root in BLOCKED:
                raise ImportError(f"sandbox blocked import: {name}")
        return _real_import(name, globals, locals, fromlist, level)

    builtins.__import__ = _safe_import

    for _name in (
        "system", "popen", "execv", "execve", "execvp", "execvpe",
        "execl", "execle", "execlp", "execlpe",
        "spawnl", "spawnle", "spawnlp", "spawnlpe", "spawnv", "spawnve",
        "spawnvp", "spawnvpe", "fork", "forkpty", "kill", "killpg",
        "remove", "unlink", "rmdir", "removedirs", "rename", "replace",
        "chmod", "chown", "symlink", "link", "truncate",
    ):
        if hasattr(os, _name):
            def _blocked(*a, _n=_name, **k):
                raise PermissionError(f"sandbox blocked os.{_n}")
            setattr(os, _name, _blocked)

    import subprocess as _subprocess

    def _sub_blocked(*a, **k):
        raise PermissionError("sandbox blocked subprocess")

    for _name in (
        "run", "Popen", "call", "check_call", "check_output",
        "getoutput", "getstatusoutput",
    ):
        if hasattr(_subprocess, _name):
            setattr(_subprocess, _name, _sub_blocked)

    for _k in list(os.environ):
        if _k.endswith("_API_KEY") or _k.endswith("_TOKEN") or _k.endswith("_SECRET"):
            os.environ.pop(_k, None)

    code_dir = sys.argv[1]
    sys.path.insert(0, code_dir)
    import app  # noqa: F401
    print("sandbox_ok")
    """
).strip()



def _preexec_limits() -> None:
    """Unix 资源软限制；失败则忽略。"""
    try:
        import resource

        cpu = max(1, int(settings.sandbox_timeout_seconds))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
        mb = int(settings.sandbox_memory_mb or 0)
        if mb > 0:
            limit = mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
        resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
        if hasattr(resource, "RLIMIT_NPROC"):
            resource.setrlimit(resource.RLIMIT_NPROC, (32, 32))
    except Exception:
        pass



def format_sandbox_import_error(
    stderr: str,
    *,
    prefix: str = "沙箱导入失败",
    max_len: int = 300,
) -> str:
    """格式化沙箱 import 失败信息：优先末尾 ModuleNotFoundError/ImportError，否则取 stderr 末尾。"""
    text = (stderr or "").strip()
    if not text:
        return f"{prefix}: （无输出）"
    for line in reversed(text.splitlines()):
        s = line.strip()
        if not s:
            continue
        if "ModuleNotFoundError" in s or "ImportError" in s:
            msg = s if len(s) <= max_len else s[-max_len:]
            return f"{prefix}: {msg}"
    tail = text if len(text) <= max_len else text[-max_len:]
    return f"{prefix}: {tail}"


def run_smoke_import_process(code_dir: Path) -> tuple[bool, str]:
    """在受限子进程中 import app；返回 (ok, message)。"""
    code_dir = code_dir.resolve()
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
        "HOME": str(code_dir),
        "TMPDIR": str(code_dir),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
    }
    timeout = max(1, int(settings.sandbox_timeout_seconds))
    try:
        proc = subprocess.run(
            [sys.executable, "-I", "-c", _RUNNER, str(code_dir)],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(code_dir),
            env=env,
            start_new_session=True,
            preexec_fn=_preexec_limits if os.name == "posix" else None,
        )
    except subprocess.TimeoutExpired as exc:
        try:
            if getattr(exc, "pid", None):
                os.killpg(exc.pid, signal.SIGKILL)
        except Exception:
            pass
        return False, f"沙箱导入超时（>{timeout}s）"
    except Exception as exc:
        return False, f"沙箱启动失败: {exc}"

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        return False, format_sandbox_import_error(err)
    if "sandbox_ok" not in (proc.stdout or ""):
        return False, "沙箱未确认成功输出"
    return True, "沙箱语法与导入检查通过"


def run_smoke_import(code_dir: Path) -> tuple[bool, str]:
    """按 sandbox_mode 选择 Docker 或进程沙箱；auto 在 Docker 不可用时回退。"""
    mode = (settings.sandbox_mode or "auto").strip().lower()
    if mode in {"docker", "auto"}:
        from app.services.docker_sandbox import docker_sandbox_ready, run_smoke_import_docker

        if docker_sandbox_ready():
            return run_smoke_import_docker(code_dir)
        if mode == "docker":
            return False, (
                "已配置 SANDBOX_MODE=docker，但本机无 Docker 或镜像不存在。"
                f"请先构建：docker build -t {settings.sandbox_docker_image} -f sandbox/Dockerfile sandbox"
            )
        # auto → fall through to process
    return run_smoke_import_process(code_dir)
