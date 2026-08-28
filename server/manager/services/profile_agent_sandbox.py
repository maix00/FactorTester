"""Fail-closed mount namespace for one server-bound Profile Agent."""

from __future__ import annotations

import os
import shutil
from pathlib import Path


class ProfileAgentSandboxError(RuntimeError):
    """A Profile Agent cannot be started with the required isolation."""


SANDBOX_WORKSPACE = Path("/workspace")


def _parents(path: Path) -> list[Path]:
    values: list[Path] = []
    current = path.parent
    while current != Path("/"):
        values.append(current)
        current = current.parent
    return list(reversed(values))


class ProfileAgentSandbox:
    """Build a Bubblewrap command exposing one Profile and private tmpfs."""

    def __init__(
        self,
        *,
        workspace_root: str | Path,
        skill_sources: list[str | Path] | None = None,
        binary: str = "bwrap",
    ) -> None:
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        self.skill_sources = sorted(
            {Path(value).expanduser().resolve() for value in (skill_sources or [])}
        )
        self.binary = str(binary or "bwrap")

    def executable(self) -> str:
        value = shutil.which(self.binary)
        if not value:
            raise ProfileAgentSandboxError(
                "bubblewrap is required for server Profile Agent isolation"
            )
        return value

    @staticmethod
    def map_workspace_path(value: str | Path) -> str:
        raw = Path(value)
        return str(SANDBOX_WORKSPACE / raw.name) if raw.is_absolute() else str(raw)

    def inside(self, value: str | Path) -> str:
        path = Path(value).expanduser().resolve()
        try:
            relative = path.relative_to(self.workspace_root)
        except ValueError:
            return str(path)
        return str(SANDBOX_WORKSPACE / relative)

    def environment(self, source: dict[str, str]) -> dict[str, str]:
        prefix = str(self.workspace_root)
        result: dict[str, str] = {}
        for key, value in source.items():
            text = str(value)
            result[key] = (
                str(SANDBOX_WORKSPACE) + text[len(prefix) :]
                if text == prefix or text.startswith(prefix + os.sep)
                else text
            )
        result["TMPDIR"] = "/tmp"
        return result

    def command(self, child: list[str]) -> list[str]:
        if not self.workspace_root.is_dir():
            raise ProfileAgentSandboxError("Profile workspace is unavailable")
        if not child:
            raise ProfileAgentSandboxError("Profile Agent command is unavailable")
        executable = shutil.which(child[0]) or child[0]
        executable_path = Path(executable)
        if not executable_path.is_absolute() or not executable_path.is_file():
            raise ProfileAgentSandboxError(
                f"Profile Agent executable is unavailable: {child[0]}"
            )
        command = [
            self.executable(),
            "--die-with-parent",
            "--new-session",
            "--unshare-all",
            "--share-net",
            "--dev",
            "/dev",
            "--tmpfs",
            "/tmp",
            "--dir",
            "/proc",
            "--dir",
            "/proc/self",
            "--symlink",
            str(executable_path),
            "/proc/self/exe",
            "--dir",
            "/workspace",
            "--bind",
            str(self.workspace_root),
            "/workspace",
        ]
        for path in ("/usr", "/opt/factortester/app"):
            if Path(path).exists():
                command.extend(["--ro-bind", path, path])
        for target, source in (
            ("/bin", "usr/bin"),
            ("/sbin", "usr/sbin"),
            ("/lib", "usr/lib"),
            ("/lib64", "usr/lib64"),
        ):
            if Path(target).is_symlink():
                command.extend(["--symlink", source, target])
            elif Path(target).exists():
                command.extend(["--ro-bind", target, target])
        for path in (
            "/etc/ca-certificates",
            "/etc/ssl",
            "/etc/resolv.conf",
            "/etc/hosts",
            "/etc/nsswitch.conf",
            "/etc/passwd",
            "/etc/group",
            "/etc/ld.so.cache",
            "/usr/local/bin/codex",
            "/usr/local/bin/codex-code-mode-host",
            "/usr/local/bin/factortester",
        ):
            if Path(path).exists():
                command.extend(["--ro-bind", path, path])
        created: set[Path] = set()
        mounted_roots = (Path("/usr"), Path("/opt/factortester/app"))
        for source in self.skill_sources:
            if not source.is_dir():
                raise ProfileAgentSandboxError(
                    f"selected Skill is unavailable: {source}"
                )
            if any(source == root or root in source.parents for root in mounted_roots):
                continue
            for parent in _parents(source):
                if parent not in created:
                    command.extend(["--dir", str(parent)])
                    created.add(parent)
            command.extend(["--ro-bind", str(source), str(source)])
        command.extend(["--chdir", "/workspace", "--", *child])
        return command


__all__ = ["SANDBOX_WORKSPACE", "ProfileAgentSandbox", "ProfileAgentSandboxError"]
