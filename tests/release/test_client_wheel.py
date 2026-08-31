from __future__ import annotations

import ast
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath

REPO_ROOT = Path(__file__).resolve().parents[2]
CLIENT_ROOT = REPO_ROOT / "tools" / "cli"
FORBIDDEN_IMPORTS = (
    "server",
    "sources",
    "tools.data",
    "tools.factors",
    "tools.parameters",
    "tools.products",
    "tools.strategies",
    "tools.testers",
)


def _build_wheel(output_dir: Path) -> Path:
    source_dir = output_dir / "source"
    shutil.copytree(
        CLIENT_ROOT,
        source_dir,
        ignore=shutil.ignore_patterns(
            "agent-harness",
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
            "--no-cache-dir",
            "--no-deps",
            "--wheel-dir",
            str(output_dir),
            str(source_dir),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    wheels = list(output_dir.glob("factortester-*.whl"))
    assert len(wheels) == 1
    return wheels[0]


def test_client_wheel_contains_only_remote_client(tmp_path: Path) -> None:
    wheel = _build_wheel(tmp_path)
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        payloads = {
            name: archive.read(name)
            for name in names
            if not name.endswith("/")
        }

    assert "tools/cli/app.py" in names
    assert "tools/cli/step/__init__.py" in names
    assert "tools/cli/step/renderer.py" in names
    assert "tools/cli/release/research_reporting/publisher/__init__.py" in names
    assert "tools/cli/release/research_reporting/publisher/service.py" in names
    assert (
        "tools/cli/release/research_reporting/authoring/__init__.py" in names
    )
    assert (
        "tools/cli/release/research_reporting/authoring/service.py" in names
    )
    assert (
        "tools/cli/release/research_reporting/maintenance/"
        "semantic_audit.py" in names
    )
    assert not [
        name for name in names
        if "/research_reporting/document/" in name
        or "/research_reporting/writer/" in name
    ]
    assert "tools/cli/release/trusted-release-public.pem" in names
    assert "tools/cli/release/trusted-beta-release-public.pem" in names
    forbidden_parts = {"tests", "agent-harness", "__pycache__", "build"}
    assert not [
        name
        for name in names
        if forbidden_parts.intersection(PurePosixPath(name).parts)
        or name.endswith(".pyc")
        or ".egg-info/" in name
    ]
    assert not [
        name
        for name in names
        if name.startswith(
            (
                "server/",
                "sources/",
                "tools/data/",
                "tools/factors/",
                "tools/testers/",
            )
        )
    ]
    assert not [
        name
        for name, payload in payloads.items()
        if b"/Users/" in payload or b"/home/" in payload
    ]

    violations: list[str] = []
    for name, payload in payloads.items():
        if not name.endswith(".py"):
            continue
        tree = ast.parse(payload, filename=name)
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        for module in imported:
            if any(
                module == prefix or module.startswith(f"{prefix}.")
                for prefix in FORBIDDEN_IMPORTS
            ):
                violations.append(f"{name}: {module}")
    assert not violations
    target_payload = payloads["tools/cli/release/client_release_targets.py"]
    assert b"scripts.release" not in target_payload


def test_built_client_runs_from_outside_repository(tmp_path: Path) -> None:
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
        [sys.executable, "-m", "tools.cli.app", "protocol", "--help"],
        cwd=tmp_path,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "negotiate" in result.stdout
    assert "show" in result.stdout

    root_help = subprocess.run(
        [sys.executable, "-m", "tools.cli.app", "--help"],
        cwd=tmp_path,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "agents" in root_help
    assert "research" in root_help
    assert "profile-agent" not in root_help

    release_target_import = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from tools.cli.release.client_release_targets import "
                "build_target_beta_package; "
                "print(build_target_beta_package.__name__)"
            ),
        ],
        cwd=tmp_path,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    assert release_target_import.stdout.strip() == "build_target_beta_package"

    products_help = subprocess.run(
        [sys.executable, "-m", "tools.cli.app", "product-library", "--help"],
        cwd=tmp_path,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    for command in ("list", "groups", "categories", "sources"):
        assert command in products_help
