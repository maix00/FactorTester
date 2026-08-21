"""OS-sandboxed execution for user-authored supplemental analysis."""

from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
import resource
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Iterable


MAX_SOURCE_BYTES = 64 * 1024
MAX_AST_NODES = 10_000
MAX_OUTPUT_BYTES = 1024 * 1024
MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 8.0
MAX_RESIDENT_BYTES = 1024 ** 3

_BLOCKED_NAMES = frozenset({
    "__builtins__", "breakpoint", "compile", "eval", "exec", "exit",
    "getattr", "globals", "help", "input", "locals", "memoryview",
    "open", "quit", "setattr", "vars",
})


class SandboxUnavailable(RuntimeError):
    """Raised instead of ever falling back to an unrestricted interpreter."""


def validate_source(source: str) -> ast.Module:
    raw = str(source).encode("utf-8")
    if not raw or len(raw) > MAX_SOURCE_BYTES:
        raise ValueError("自定义分析代码必须为 1–65536 字节")
    try:
        tree = ast.parse(str(source), filename="custom_analysis.py", mode="exec")
    except SyntaxError as exc:
        raise ValueError(f"Python 语法错误: {exc.msg}") from exc
    nodes = list(ast.walk(tree))
    if len(nodes) > MAX_AST_NODES:
        raise ValueError("自定义分析代码过于复杂")
    result_assigned = False
    for node in nodes:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            raise ValueError("自定义分析不允许 import；请使用预置的 math/statistics/json")
        if isinstance(node, ast.Attribute) and str(node.attr).startswith("_"):
            raise ValueError("自定义分析不能访问私有或特殊属性")
        if isinstance(node, ast.Name) and node.id in _BLOCKED_NAMES:
            raise ValueError(f"自定义分析不能使用 {node.id}")
        if isinstance(node, ast.Name) and node.id == "result" and isinstance(
            node.ctx, (ast.Store, ast.Del),
        ):
            result_assigned = True
    if not result_assigned:
        raise ValueError("自定义分析必须给 result 赋值")
    return tree


def _verified_artifacts(values: Iterable[dict[str, Any]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    names: set[str] = set()
    for value in values:
        name = str(value.get("name") or "").strip()
        path = Path(value.get("path") or "").expanduser().resolve()
        expected = str(value.get("content_hash") or "").strip()
        if not name or name in names or not path.is_file() or not expected:
            raise ValueError("自定义分析生成物清单无效")
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise RuntimeError(f"生成物完整性校验失败: {name}")
        if path.stat().st_size > MAX_ARTIFACT_BYTES:
            raise ValueError(f"生成物过大，不能用于自定义分析: {name}")
        names.add(name)
        result.append({
            "name": name,
            "path": str(path),
            "content_hash": expected,
            "content_type": str(value.get("content_type") or ""),
        })
    return result


def _limits() -> None:
    def lower(which: int, requested: int) -> None:
        _soft, hard = resource.getrlimit(which)
        limit = requested if hard == resource.RLIM_INFINITY else min(requested, hard)
        # Preserve the inherited hard limit.  Python 3.14 on macOS exposes
        # RLIM_INFINITY as a value the kernel rejects when it is written back
        # as a new hard limit, even though lowering only the soft limit works.
        resource.setrlimit(which, (limit, hard))

    lower(resource.RLIMIT_CPU, 4)
    # Linux enforces the address-space ceiling in-kernel. macOS rejects every
    # documented memory RLIMIT when launched from current Conda runtimes, so
    # the parent watchdog below enforces resident memory there instead.
    if sys.platform != "darwin":
        lower(resource.RLIMIT_AS, MAX_RESIDENT_BYTES)
    lower(resource.RLIMIT_FSIZE, MAX_OUTPUT_BYTES)
    lower(resource.RLIMIT_NOFILE, 64)
    os.umask(0o077)


def _linux_command(
    python: str, harness: Path, artifacts: list[dict[str, str]],
) -> tuple[list[str], dict[str, str]]:
    bwrap = shutil.which("bwrap")
    if not bwrap:
        raise SandboxUnavailable("Linux bubblewrap 不可用，拒绝执行自定义代码")
    command = [
        bwrap, "--die-with-parent", "--new-session", "--unshare-all",
        "--clearenv", "--proc", "/proc", "--dev", "/dev", "--dir", "/tmp",
        "--dir", "/artifacts", "--ro-bind", str(harness), "/runner.py",
    ]
    for root in ("/usr", "/bin", "/lib", "/lib64", "/etc/ld.so.cache"):
        if Path(root).exists():
            command.extend(("--ro-bind", root, root))
    prefix = Path(sys.prefix).resolve()
    if prefix not in {Path("/usr"), Path("/usr/local")} and not str(prefix).startswith("/usr/"):
        command.extend(("--ro-bind", str(prefix), str(prefix)))
    virtual: dict[str, str] = {}
    for index, artifact in enumerate(artifacts):
        target = f"/artifacts/{index:04d}.artifact"
        command.extend(("--ro-bind", artifact["path"], target))
        virtual[artifact["name"]] = target
    command.extend(("--", python, "-I", "/runner.py"))
    return command, virtual


def _mac_profile(
    profile: Path, harness: Path, artifacts: list[dict[str, str]],
) -> None:
    readable = {
        str(harness), str(harness.resolve()),
        str(sys.executable), str(Path(sys.executable).resolve()),
    }
    readable.update(item["path"] for item in artifacts)
    subpaths = {
        str(Path(sys.prefix).resolve()), str(Path(sys.base_prefix).resolve()),
        "/System/Library", "/System/Volumes/Preboot/Cryptexes", "/usr/lib",
        "/Library/Apple", "/private/var/db", "/dev",
    }
    rules = [
        "(version 1)", "(deny default)", '(import "system.sb")',
        "(allow process-exec)",
        "(deny process-fork)", "(allow sysctl-read)", "(allow mach-lookup)",
        "(allow file-read-metadata)",
    ]
    rules.extend(
        f'(allow file-read-data (literal {json.dumps(path)}))'
        for path in sorted(readable)
    )
    rules.extend(
        f'(allow file-read* (subpath {json.dumps(path)}))'
        for path in sorted(subpaths) if Path(path).exists()
    )
    profile.write_text("\n".join(rules) + "\n", encoding="utf-8")


def _mac_command(
    python: str, harness: Path, artifacts: list[dict[str, str]], profile: Path,
) -> tuple[list[str], dict[str, str]]:
    sandbox = shutil.which("sandbox-exec")
    if not sandbox:
        raise SandboxUnavailable("macOS sandbox-exec 不可用，拒绝执行自定义代码")
    _mac_profile(profile, harness, artifacts)
    return [sandbox, "-f", str(profile), python, "-I", str(harness)], {
        item["name"]: item["path"] for item in artifacts
    }


def _mac_resident_bytes(pid: int) -> int:
    try:
        value = subprocess.run(
            ["/bin/ps", "-o", "rss=", "-p", str(pid)],
            capture_output=True, text=True, check=False, timeout=1,
            env={"PATH": "/usr/bin:/bin"},
        ).stdout.strip()
        return max(0, int(value or 0)) * 1024
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0


def _run_process(
    command: list[str], payload: bytes, stdout, stderr, timeout_seconds: float,
) -> tuple[int, bool]:
    process = subprocess.Popen(
        command, stdin=subprocess.PIPE, stdout=stdout, stderr=stderr,
        env={"PYTHONDONTWRITEBYTECODE": "1", "PYTHONHASHSEED": "0"},
        preexec_fn=_limits,
    )
    memory_exceeded = threading.Event()
    stopped = threading.Event()

    def watch_memory() -> None:
        if sys.platform != "darwin":
            return
        while not stopped.wait(0.05):
            if _mac_resident_bytes(process.pid) > MAX_RESIDENT_BYTES:
                memory_exceeded.set()
                process.kill()
                return

    watcher = threading.Thread(target=watch_memory, daemon=True)
    watcher.start()
    try:
        process.communicate(payload, timeout=max(1.0, float(timeout_seconds)))
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.communicate()
        raise TimeoutError("自定义分析运行超时") from exc
    finally:
        stopped.set()
        watcher.join(timeout=0.2)
    return int(process.returncode or 0), memory_exceeded.is_set()


def run_custom_python(
    source: str,
    artifacts: Iterable[dict[str, Any]],
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Execute validated source and return its bounded structured result."""
    validate_source(source)
    verified = _verified_artifacts(artifacts)
    harness_source = Path(__file__).with_name("custom_python_harness.py").read_text(
        encoding="utf-8",
    )
    with tempfile.TemporaryDirectory(prefix="ft-custom-analysis-") as directory:
        root = Path(directory)
        harness = root / "runner.py"
        harness.write_text(harness_source, encoding="utf-8")
        profile = root / "sandbox.sb"
        python = str(Path(sys.executable).resolve())
        if sys.platform.startswith("linux"):
            command, virtual = _linux_command(python, harness, verified)
        elif sys.platform == "darwin":
            command, virtual = _mac_command(python, harness, verified, profile)
        else:
            raise SandboxUnavailable("当前系统没有受支持的自定义分析沙箱")
        payload = json.dumps({
            "source": str(source),
            "artifacts": virtual,
            "max_artifact_bytes": MAX_ARTIFACT_BYTES,
        }).encode()
        stdout_path = root / "stdout.json"
        stderr_path = root / "stderr.txt"
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            returncode, memory_exceeded = _run_process(
                command, payload, stdout, stderr, timeout_seconds,
            )
        raw = stdout_path.read_bytes()[:MAX_OUTPUT_BYTES + 1]
        error = stderr_path.read_text(encoding="utf-8", errors="replace")[:4096]
        if len(raw) > MAX_OUTPUT_BYTES:
            raise RuntimeError("自定义分析输出超过限制")
        if memory_exceeded:
            raise MemoryError("自定义分析内存占用超过限制")
        if returncode != 0:
            raise RuntimeError(error.strip() or f"自定义分析退出码 {returncode}")
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError("自定义分析没有返回有效的结构化结果") from exc
        if not isinstance(value, dict) or value.get("success") is not True:
            raise RuntimeError(str(value.get("error") if isinstance(value, dict) else value))
        return {"result": value.get("result"), "logs": list(value.get("logs") or ())}
