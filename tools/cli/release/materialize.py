"""Offline materialization of verified client release artifacts."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import uuid

from .app_archive import install_macos_app


MAX_INSTALL_OUTPUT_BYTES = 64 * 1024
COMMAND_MODULES = {
    "traderesearch": ("tools.cli.app", "cli"),
    "traderesearch-manager": ("tools.cli.manager_app", "manager_cli"),
}
STABLE_COMMANDS = (
    "traderesearch",
    "traderesearch-manager",
)
ENV_SCRIPT = "traderesearch-env.sh"
LEGACY_COMMANDS = ("factortester", "factortester-manager")
LEGACY_ENV_SCRIPT = "factortester-env.sh"


def materialize_release(
    staging: Path,
    asset_receipts: list[dict],
) -> dict:
    artifacts = staging / "artifacts"
    wheel_names = [
        item["filename"]
        for item in asset_receipts
        if item["kind"] == "python-wheel"
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
    version = _current_version(root)
    bin_root = root / "bin"
    bin_root.mkdir(parents=True, exist_ok=True)
    remove_generated_legacy_launchers(root)
    for command in STABLE_COMMANDS:
        target = bin_root / command
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("x", encoding="utf-8") as handle:
                handle.write(_launcher(root, version, command))
                handle.flush()
                os.fsync(handle.fileno())
            temporary.chmod(0o755)
            os.replace(temporary, target)
            target.chmod(0o755)
        finally:
            if temporary.exists():
                temporary.unlink()
    env_target = bin_root / ENV_SCRIPT
    temporary = env_target.with_name(f".{env_target.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            handle.write(_environment_script(root))
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(0o755)
        os.replace(temporary, env_target)
        env_target.chmod(0o755)
    finally:
        if temporary.exists():
            temporary.unlink()
    descriptor = os.open(bin_root, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def stable_launchers_are_current(root: Path) -> bool:
    version = _current_version(root, required=False)
    if not version:
        return False
    if any(
        (root / "bin" / command).exists()
        or (root / "bin" / command).is_symlink()
        for command in LEGACY_COMMANDS
    ):
        return False
    if (
        (root / "bin" / LEGACY_ENV_SCRIPT).exists()
        or (root / "bin" / LEGACY_ENV_SCRIPT).is_symlink()
    ):
        return False
    for command in STABLE_COMMANDS:
        target = root / "bin" / command
        if (
            not target.is_file()
            or not os.access(target, os.X_OK)
            or target.read_text(encoding="utf-8")
            != _launcher(root, version, command)
        ):
            return False
    env_target = root / "bin" / ENV_SCRIPT
    return (
        env_target.is_file()
        and os.access(env_target, os.X_OK)
        and env_target.read_text(encoding="utf-8")
        == _environment_script(root)
    )


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


def _current_version(root: Path, *, required: bool = True) -> str:
    try:
        payload = json.loads((root / "current.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        if required:
            raise ValueError("active client release pointer is missing") from error
        return ""
    version = str(payload.get("version") or "").strip()
    if not version and required:
        raise ValueError("active client release version is missing")
    return version


def _launcher(root: Path, version: str, command: str) -> str:
    # New releases carry canonical executable names. Read old names only inside
    # an already-installed, verified bundle so the public CLI surface has one
    # spelling without forcing users to reinstall an older signed client first.
    legacy_name = {
        "traderesearch": "factortester",
        "traderesearch-manager": "factortester-manager",
    }.get(command)
    names = [command, *([legacy_name] if legacy_name else [])]
    candidates = [
        root / "releases" / version / "runtime" / runtime / "bin" / name
        for runtime in ("standalone", "python")
        for name in names
    ]
    checks = "".join(
        f"candidate_{index}={shlex.quote(str(candidate))}\n"
        f"if [ -x \"$candidate_{index}\" ]; then\n"
        f"  exec \"$candidate_{index}\" \"$@\"\n"
        "fi\n"
        for index, candidate in enumerate(candidates)
    )
    return (
        "#!/bin/sh\n"
        "set -eu\n"
        + checks
        + f"echo 'TradeResearch release command is unavailable: {command}' >&2\n"
        + "exit 127\n"
    )


def _environment_script(root: Path) -> str:
    bin_root = shlex.quote(str(root / "bin"))
    client_root = shlex.quote(str(root))
    cli = shlex.quote(str(root / "bin" / "traderesearch"))
    manager = shlex.quote(str(root / "bin" / "traderesearch-manager"))
    return (
        "#!/bin/sh\n"
        "# Source this file; executing it cannot change the parent shell.\n"
        f"TRADERESEARCH_CLIENT_ROOT={client_root}\n"
        f"TRADERESEARCH_CLIENT_BIN={bin_root}\n"
        f"TRADERESEARCH_CLI={cli}\n"
        f"TRADERESEARCH_MANAGER_CLI={manager}\n"
        f"TRADERESEARCH_RESEARCH_CLI={cli}\n"
        "export TRADERESEARCH_CLIENT_ROOT TRADERESEARCH_CLIENT_BIN\n"
        "export TRADERESEARCH_CLI TRADERESEARCH_MANAGER_CLI\n"
        "export TRADERESEARCH_RESEARCH_CLI\n"
        "case :${PATH:-}: in\n"
        "  *:\"$TRADERESEARCH_CLIENT_BIN\":*) ;;\n"
        "  *) PATH=\"$TRADERESEARCH_CLIENT_BIN${PATH:+:$PATH}\" ;;\n"
        "esac\n"
        "export PATH\n"
    )


def remove_generated_legacy_launchers(root: Path) -> None:
    """Remove only the exact aliases generated by previous client releases."""
    bin_root = root / "bin"
    versions_root = root / "releases"
    versions = (
        [path.name for path in versions_root.iterdir() if path.is_dir()]
        if versions_root.is_dir()
        else []
    )
    for command in LEGACY_COMMANDS:
        target = bin_root / command
        if not target.exists() and not target.is_symlink():
            continue
        if target.is_symlink() or not target.is_file():
            raise ValueError(
                f"refusing to remove unexpected legacy CLI launcher: {target}"
            )
        generated_versions = {
            _legacy_launcher(root, version, command) for version in versions
        }
        if target.read_text(encoding="utf-8") not in generated_versions:
            raise ValueError(
                f"refusing to remove non-generated legacy CLI launcher: {target}"
            )
        target.unlink()

    target = bin_root / LEGACY_ENV_SCRIPT
    if target.exists() or target.is_symlink():
        if target.is_symlink() or not target.is_file():
            raise ValueError(
                f"refusing to remove unexpected legacy CLI environment file: {target}"
            )
        if target.read_text(encoding="utf-8") != _legacy_environment_script(root):
            raise ValueError(
                f"refusing to remove non-generated legacy CLI environment file: {target}"
            )
        target.unlink()


def _legacy_launcher(root: Path, version: str, command: str) -> str:
    standalone = (
        root / "releases" / version / "runtime" / "standalone" / "bin" / command
    )
    python = root / "releases" / version / "runtime" / "python" / "bin" / command
    return (
        "#!/bin/sh\n"
        "set -eu\n"
        f"standalone={shlex.quote(str(standalone))}\n"
        f"legacy={shlex.quote(str(python))}\n"
        "if [ -x \"$standalone\" ]; then\n"
        "  exec \"$standalone\" \"$@\"\n"
        "fi\n"
        "if [ -x \"$legacy\" ]; then\n"
        "  exec \"$legacy\" \"$@\"\n"
        "fi\n"
        f"echo 'TradeResearch release command is unavailable: {command}' >&2\n"
        "exit 127\n"
    )


def _legacy_environment_script(root: Path) -> str:
    bin_root = shlex.quote(str(root / "bin"))
    client_root = shlex.quote(str(root))
    cli = shlex.quote(str(root / "bin" / "factortester"))
    manager = shlex.quote(str(root / "bin" / "factortester-manager"))
    return (
        "#!/bin/sh\n"
        "# Source this file; executing it cannot change the parent shell.\n"
        f"FACTORTESTER_CLIENT_ROOT={client_root}\n"
        f"FACTORTESTER_CLIENT_BIN={bin_root}\n"
        f"FACTORTESTER_CLI={cli}\n"
        f"FACTORTESTER_MANAGER_CLI={manager}\n"
        f"FACTORTESTER_RESEARCH_CLI={cli}\n"
        "export FACTORTESTER_CLIENT_ROOT FACTORTESTER_CLIENT_BIN\n"
        "export FACTORTESTER_CLI FACTORTESTER_MANAGER_CLI\n"
        "export FACTORTESTER_RESEARCH_CLI\n"
        "case :${PATH:-}: in\n"
        "  *:\"$FACTORTESTER_CLIENT_BIN\":*) ;;\n"
        "  *) PATH=\"$FACTORTESTER_CLIENT_BIN${PATH:+:$PATH}\" ;;\n"
        "esac\n"
        "export PATH\n"
    )
