from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CommandResult:
    argv: list[str]
    returncode: int
    stdout: str
    stderr: str

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "argv": self.argv,
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
        }
        try:
            payload["json"] = json.loads(self.stdout)
        except Exception:
            pass
        return payload


def resolve_factortester() -> str:
    executable = shutil.which("factortester")
    if not executable:
        raise RuntimeError("factortester command not found; install/configure the FactorTester client first")
    return executable


def run_factortester(args: list[str], *, timeout: int = 600) -> CommandResult:
    executable = resolve_factortester()
    argv = [executable, *args]
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
    return CommandResult(argv=argv, returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)


def looks_like_platform_gap(result: CommandResult) -> bool:
    text = f"{result.stdout}\n{result.stderr}".lower()
    needles = (
        "no such command",
        "not implemented",
        "unsupported",
        "不支持",
        "未实现",
        "未知字段",
        "missing registered",
        "缺少注册",
    )
    return result.returncode != 0 and any(item in text for item in needles)
