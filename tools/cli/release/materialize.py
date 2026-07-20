"""Offline materialization of verified client release artifacts."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

from .app_archive import install_macos_app


MAX_INSTALL_OUTPUT_BYTES = 64 * 1024
COMMAND_MODULES = {
    "factortester": ("tools.cli.app", "cli"),
    "cli-anything-factortester-research": (
        "cli_anything.factortester_research.factortester_research_cli",
        "cli",
    ),
}


def materialize_release(
    staging: Path,
    asset_receipts: list[dict],
) -> dict:
    artifacts = staging / "artifacts"
    wheel_names = [
        item["filename"]
        for item in asset_receipts
        if item["kind"] in {"python-wheel", "harness-wheel"}
    ]
    result: dict[str, object] = {"schema_version": 1}
    if wheel_names:
        result["python"] = _install_wheels(staging, artifacts, wheel_names)
    app_names = [
        item["filename"]
        for item in asset_receipts
        if item["kind"] == "macos-app"
    ]
    if len(app_names) > 1:
        raise ValueError("release contains multiple macOS application assets")
    if app_names:
        result["macos_app"] = install_macos_app(
            artifacts / app_names[0],
            staging / "applications",
        )
    return result


def install_stable_launchers(root: Path) -> None:
    bin_root = root / "bin"
    bin_root.mkdir(parents=True, exist_ok=True)
    for command in ("factortester", "cli-anything-factortester-research"):
        target = bin_root / command
        target.write_text(_launcher(root, command), encoding="utf-8")
        target.chmod(0o755)


def _install_wheels(
    staging: Path,
    artifacts: Path,
    wheel_names: list[str],
) -> dict:
    runtime = staging / "runtime" / "python"
    packages = runtime / "site-packages"
    packages.mkdir(parents=True)
    wheels = [str(artifacts / name) for name in wheel_names]
    result = subprocess.run(
        [
            sys.executable, "-m", "pip", "install",
            "--disable-pip-version-check", "--no-index",
            "--no-deps",
            "--find-links", str(artifacts),
            "--target", str(packages), *wheels,
        ],
        capture_output=True,
        check=False,
        timeout=300,
    )
    if result.returncode:
        detail = result.stderr[-MAX_INSTALL_OUTPUT_BYTES:].decode(
            "utf-8", errors="replace"
        )
        raise ValueError(f"offline wheel installation failed: {detail}")
    installed = []
    for command, (module, function) in COMMAND_MODULES.items():
        if _module_exists(packages, module):
            executable = _write_runtime_command(
                runtime, command, module, function
            )
            _verify_command(executable)
            installed.append(command)
    if not installed:
        raise ValueError("release wheels installed no supported client command")
    return {
        "runtime": "runtime/python",
        "commands": installed,
        "wheel_count": len(wheel_names),
    }


def _module_exists(packages: Path, module: str) -> bool:
    parts = module.split(".")
    return (
        packages.joinpath(*parts).with_suffix(".py").is_file()
        or packages.joinpath(*parts, "__init__.py").is_file()
    )


def _write_runtime_command(
    runtime: Path,
    command: str,
    module: str,
    function: str,
) -> Path:
    executable = runtime / "bin" / command
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.write_text(
        f"#!{sys.executable}\n"
        "import sys\n"
        "from pathlib import Path\n"
        "sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'site-packages'))\n"
        f"from {module} import {function}\n"
        f"{function}()\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    return executable


def _verify_command(executable: Path) -> None:
    result = subprocess.run(
        [str(executable), "--help"],
        capture_output=True,
        check=False,
        timeout=30,
    )
    if result.returncode:
        raise ValueError(f"installed command health check failed: {executable.name}")


def _launcher(root: Path, command: str) -> str:
    encoded_root = json.dumps(str(root))
    encoded_command = json.dumps(command)
    return (
        "#!/usr/bin/env python3\n"
        "import json, os\n"
        "from pathlib import Path\n"
        f"root = Path({encoded_root})\n"
        "current = json.loads((root / 'current.json').read_text())['version']\n"
        f"program = root / 'releases' / current / 'runtime/python/bin' / {encoded_command}\n"
        "os.execv(str(program), [str(program), *os.sys.argv[1:]])\n"
    )
