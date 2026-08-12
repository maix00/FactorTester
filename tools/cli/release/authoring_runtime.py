"""Hermetic authoring metadata and Pyright runtime for factor worktrees."""

from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
from typing import Any


AUTHORING_CONTRACT_ID = "factortester-authoring-sdk@1"
PYRIGHT_VERSION = "1.1.411"
_MANAGED_PATHS = frozenset({
    "pyrightconfig.json",
    "tools/factors/Parameters.pyi",
})
_OPERATIONAL_PATHS = frozenset({
    ".factor_workspace/",
    ".factor_workspace/manifest.json",
})
_PARAMETER_IMPORT = "from tools.parameters.Parameter import Parameter"
_PARAMETER_MARKER = "from enum import Enum\n"


def refresh_authoring_metadata(worktree: Path) -> dict[str, Any]:
    """Bring generated authoring metadata to the bundled client contract.

    Only generated metadata is writable here. Factor source, policies, public
    factors, and unknown SDK paths are intentionally outside this contract.
    """
    root = worktree.resolve()
    before_status = authoring_status_paths(root)
    if before_status:
        raise ValueError(
            "factor worktree must be clean before authoring metadata refresh"
        )
    before = {
        relative: _optional_hash(root / relative)
        for relative in sorted(_MANAGED_PATHS)
    }
    _refresh_pyright_config(root / "pyrightconfig.json")
    _refresh_parameters_stub(root / "tools/factors/Parameters.pyi")
    changed = authoring_status_paths(root)
    unexpected = changed - _MANAGED_PATHS
    if unexpected:
        raise ValueError(
            "authoring metadata refresh touched unmanaged paths: "
            + ", ".join(sorted(unexpected))
        )
    files = []
    for relative in sorted(changed):
        target = root / relative
        files.append({
            "path": relative,
            "before_sha256": before[relative],
            "after_sha256": _required_hash(target),
        })
    return {
        "schema_version": 1,
        "contract_id": AUTHORING_CONTRACT_ID,
        "managed_paths": sorted(_MANAGED_PATHS),
        "changed_paths": sorted(changed),
        "files": files,
        "pyright_version": PYRIGHT_VERSION,
    }


def run_bundled_pyright(worktree: Path) -> dict[str, Any]:
    """Run the release-bundled Pyright and Node runtime without PATH/network."""
    try:
        import pyright
        from pyright import cli as pyright_cli
        import nodejs_wheel  # noqa: F401
    except ImportError as exc:
        raise ValueError(
            "verified bundled Pyright runtime is unavailable"
        ) from exc
    observed = str(getattr(pyright, "__pyright_version__", ""))
    if observed != PYRIGHT_VERSION:
        raise ValueError(
            f"bundled Pyright version mismatch: {observed or 'missing'}"
        )
    root = worktree.resolve()
    environment = {
        **os.environ,
        "PATH": "",
        "PYRIGHT_PYTHON_GLOBAL_NODE": "0",
        "PYRIGHT_PYTHON_NODEJS_WHEEL": "1",
        "PYRIGHT_PYTHON_USE_BUNDLED_PYRIGHT": "1",
        "PYRIGHT_PYTHON_IGNORE_WARNINGS": "1",
        "PYRIGHT_PYTHON_FORCE_VERSION": PYRIGHT_VERSION,
        "FACTOR_WORKSPACE_SKIP_AUTOSYNC": "1",
        "GIT_TERMINAL_PROMPT": "0",
    }
    result = pyright_cli.run(
        "--project",
        str(root / "pyrightconfig.json"),
        "--outputjson",
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    try:
        payload = json.loads(result.stdout or "{}")
    except ValueError as exc:
        raise ValueError("bundled Pyright returned invalid JSON") from exc
    summary = payload.get("summary") if isinstance(payload, dict) else None
    if not isinstance(summary, dict):
        raise ValueError("bundled Pyright result has no summary")
    return {
        "version": observed,
        "returncode": result.returncode,
        "files_analyzed": int(summary.get("filesAnalyzed") or 0),
        "error_count": int(summary.get("errorCount") or 0),
        "warning_count": int(summary.get("warningCount") or 0),
    }


def _refresh_pyright_config(path: Path) -> None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("factor worktree pyrightconfig.json is invalid") from exc
    if not isinstance(value, dict):
        raise ValueError("factor worktree pyrightconfig.json must be an object")
    if value.get("pythonVersion") == "3.10":
        return
    value["pythonVersion"] = "3.10"
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _refresh_parameters_stub(path: Path) -> None:
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    if _PARAMETER_IMPORT in text:
        return
    if "Parameter" not in text or _PARAMETER_MARKER not in text:
        raise ValueError(
            "generated Parameters.pyi is incompatible with authoring contract"
        )
    path.write_text(
        text.replace(
            _PARAMETER_MARKER,
            _PARAMETER_MARKER + _PARAMETER_IMPORT + "\n",
            1,
        ),
        encoding="utf-8",
    )


def authoring_status_paths(root: Path) -> set[str]:
    result = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain=v1", "-z"],
        env={
            **os.environ,
            "FACTOR_WORKSPACE_SKIP_AUTOSYNC": "1",
            "GIT_TERMINAL_PROMPT": "0",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise ValueError("cannot inspect factor worktree authoring changes")
    paths = set()
    for entry in filter(None, result.stdout.split("\0")):
        raw = entry[3:]
        if " -> " in raw:
            raw = raw.rsplit(" -> ", 1)[1]
        paths.add(raw)
    return paths - _OPERATIONAL_PATHS


def _optional_hash(path: Path) -> str | None:
    return _required_hash(path) if path.is_file() else None


def _required_hash(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"managed authoring file is invalid: {path.name}")
    return sha256(path.read_bytes()).hexdigest()
