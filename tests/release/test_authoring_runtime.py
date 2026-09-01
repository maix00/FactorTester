from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from types import ModuleType, SimpleNamespace

from tools.cli.release.authoring_runtime import (
    refresh_authoring_metadata,
    run_bundled_pyright,
)


def _git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *arguments],
        env={**os.environ, "FACTOR_WORKSPACE_SKIP_AUTOSYNC": "1"},
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _stale_workspace(root: Path) -> Path:
    root.mkdir()
    _git(root, "init", "-b", "download")
    _git(root, "config", "user.email", "tests@example.invalid")
    _git(root, "config", "user.name", "Tests")
    (root / "custom_factors").mkdir()
    (root / "custom_factors/Keep.py").write_text("value = 1\n")
    (root / "tools/factors").mkdir(parents=True)
    (root / "tools/factors/Parameters.pyi").write_text(
        "from __future__ import annotations\n"
        "from typing import Any\n"
        "from enum import Enum\n\n"
        "RemovedLegacyParam: Parameter = ...\n"
    )
    (root / "pyrightconfig.json").write_text(json.dumps({
        "include": ["custom_factors", "tools"],
        "reportMissingModuleSource": "none",
    }))
    _git(root, "add", ".")
    _git(root, "commit", "-m", "stale authoring metadata")
    return root


def test_refresh_is_narrow_deterministic_and_idempotent(tmp_path: Path) -> None:
    workspace = _stale_workspace(tmp_path / "workspace")
    source_before = (workspace / "custom_factors/Keep.py").read_bytes()

    first = refresh_authoring_metadata(workspace)
    second_status = _git(workspace, "status", "--porcelain")
    _git(workspace, "add", "--", *first["changed_paths"])
    _git(workspace, "commit", "-m", "generated baseline")
    second = refresh_authoring_metadata(workspace)

    assert first["changed_paths"] == [
        "pyrightconfig.json",
        "tools/factors/Parameters.pyi",
    ]
    assert second_status
    assert second["changed_paths"] == []
    assert (workspace / "custom_factors/Keep.py").read_bytes() == source_before
    assert json.loads((workspace / "pyrightconfig.json").read_text())[
        "pythonVersion"
    ] == "3.10"
    assert (
        "from tools.parameters.Parameter import Parameter"
        in (workspace / "tools/factors/Parameters.pyi").read_text()
    )


def test_bundled_pyright_ignores_empty_path_and_uses_pinned_runtime(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "pyrightconfig.json").write_text("{}")
    captured = {}

    pyright = ModuleType("pyright")
    pyright.__pyright_version__ = "1.1.411"
    cli = ModuleType("pyright.cli")

    def run(*arguments, **kwargs):
        captured["arguments"] = arguments
        captured["kwargs"] = kwargs
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({
                "summary": {
                    "filesAnalyzed": 93,
                    "errorCount": 0,
                    "warningCount": 0,
                }
            }),
        )

    cli.run = run
    pyright.cli = cli
    monkeypatch.setitem(sys.modules, "pyright", pyright)
    monkeypatch.setitem(sys.modules, "pyright.cli", cli)
    monkeypatch.setitem(sys.modules, "nodejs_wheel", ModuleType("nodejs_wheel"))
    monkeypatch.setenv("PATH", "/untrusted/global/path")

    result = run_bundled_pyright(workspace)

    assert result == {
        "version": "1.1.411",
        "returncode": 0,
        "files_analyzed": 93,
        "error_count": 0,
        "warning_count": 0,
    }
    assert captured["kwargs"]["env"]["PATH"] == ""
    assert captured["kwargs"]["env"]["PYRIGHT_PYTHON_GLOBAL_NODE"] == "0"
    assert captured["kwargs"]["env"]["PYRIGHT_PYTHON_NODEJS_WHEEL"] == "1"
    assert "--outputjson" in captured["arguments"]
