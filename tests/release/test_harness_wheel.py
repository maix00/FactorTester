from __future__ import annotations

import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import zipfile


REPO_ROOT = Path(__file__).resolve().parents[2]
HARNESS_ROOT = REPO_ROOT / "tools" / "cli" / "agent-harness"
PACKAGE_ROOT = "cli_anything/factortester_research/"


def _build_wheel(output_dir: Path) -> Path:
    source_dir = output_dir / "source"
    shutil.copytree(
        HARNESS_ROOT,
        source_dir,
        ignore=shutil.ignore_patterns(
            "build",
            "dist",
            "*.egg-info",
            "__pycache__",
            "*.pyc",
        ),
    )
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--no-cache-dir",
            "--wheel-dir",
            str(output_dir),
            str(source_dir),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    wheels = list(output_dir.glob("*.whl"))
    assert len(wheels) == 1
    return wheels[0]


def test_harness_wheel_is_relocatable_release_artifact(tmp_path: Path) -> None:
    wheel = _build_wheel(tmp_path)

    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        payloads = {
            name: archive.read(name)
            for name in names
            if not name.endswith("/")
        }

    assert f"{PACKAGE_ROOT}skills/SKILL.md" in names
    assert (
        f"{PACKAGE_ROOT}skills/research-obligation-cycle/SKILL.md"
        in names
    )
    assert f"{PACKAGE_ROOT}resources/capabilities.v1.json" in names
    assert f"{PACKAGE_ROOT}resources/provider-locks.v1.json" in names

    forbidden_parts = {"tests", "__pycache__", "build"}
    assert not [
        name
        for name in names
        if forbidden_parts.intersection(PurePosixPath(name).parts)
        or name.endswith(".pyc")
        or ".egg-info/" in name
    ]
    assert not [
        name
        for name, payload in payloads.items()
        if b"/Users/" in payload or b"/home/" in payload
    ]

    provider_locks = json.loads(
        payloads[
            f"{PACKAGE_ROOT}resources/provider-locks.v1.json"
        ]
    )
    for provider in provider_locks["providers"].values():
        assert not str(provider.get("root_hint") or "").startswith("/")
    for implementation in provider_locks["implementations"].values():
        assert not str(implementation.get("root_hint") or "").startswith("/")


def test_built_harness_runs_from_outside_repository(tmp_path: Path) -> None:
    wheel = _build_wheel(tmp_path)
    install_root = tmp_path / "installed"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--target",
            str(install_root),
            str(wheel),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(install_root)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "cli_anything.factortester_research",
            "--help",
        ],
        cwd=tmp_path,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "cli_anything.factortester_research" in result.stdout
    assert "workspace" in result.stdout
    assert "cycle" in result.stdout
