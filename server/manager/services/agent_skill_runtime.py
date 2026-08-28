"""Per-Profile Codex runtime isolation and Skill projection."""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any


SKILL_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
RUNTIME_MANIFEST_VERSION = 1
CODEX_SYSTEM_SKILLS_DIRNAME = ".system"
CODEX_SYSTEM_SKILLS_MARKER = ".codex-system-skills.marker"


class AgentSkillRuntimeError(ValueError):
    """A Profile Skill projection or runtime environment is invalid."""


class AgentSkillRuntime:
    """Own one persistent ``.codex`` projection inside a Profile workspace.

    The source Skill directories remain server-owned.  The Profile receives
    only symlinks to the selected directories, which keeps the workspace
    small while making the app-server's visible Skill root deterministic.
    """

    def __init__(self, workspace_root: str | Path) -> None:
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        self.codex_home = self.workspace_root / ".codex"
        self.skills_root = self.codex_home / "skills"
        self.home_root = self.codex_home / "home"
        self.config_root = self.codex_home / "config"
        self.data_root = self.codex_home / "data"
        self.state_root = self.codex_home / "state"
        self.factor_tester_client_root = (
            self.workspace_root / ".factortester-client"
        )
        self.manifest_path = self.codex_home / "factortester-skill-projection.json"

    @staticmethod
    def _text(value: object, field: str) -> str:
        result = str(value or "").strip()
        if not result:
            raise AgentSkillRuntimeError(f"{field} is required")
        if len(result) > 256:
            raise AgentSkillRuntimeError(f"{field} is too long")
        return result

    @classmethod
    def _binding(cls, value: object) -> dict[str, str]:
        if not isinstance(value, Mapping):
            raise AgentSkillRuntimeError("Skill binding must be an object")
        skill_id = cls._text(value.get("skill_id"), "skill_id")
        name = cls._text(value.get("name"), "Skill name")
        if not SKILL_ID_PATTERN.fullmatch(skill_id):
            raise AgentSkillRuntimeError("Skill id is invalid")
        if not SKILL_ID_PATTERN.fullmatch(name):
            raise AgentSkillRuntimeError("Skill name is invalid")
        source = Path(cls._text(value.get("path"), "Skill path")).expanduser().resolve()
        if not source.is_dir() or not (source / "SKILL.md").is_file():
            raise AgentSkillRuntimeError(f"installed Skill is missing: {source}")
        return {
            "skill_id": skill_id,
            "name": name,
            "source_path": str(source),
        }

    def _prepare_directories(self) -> None:
        self.codex_home.mkdir(parents=True, exist_ok=True)
        for path in (
            self.skills_root,
            self.home_root,
            self.config_root,
            self.data_root,
            self.state_root,
            self.factor_tester_client_root,
        ):
            path.mkdir(parents=True, exist_ok=True)
        for path in (
            self.workspace_root,
            self.codex_home,
            self.skills_root,
            self.home_root,
            self.config_root,
            self.data_root,
            self.state_root,
            self.factor_tester_client_root,
        ):
            try:
                os.chmod(path, 0o700)
            except OSError:
                # Windows and some mounted data volumes do not support chmod.
                pass

    def _read_manifest(self) -> dict[str, dict[str, str]]:
        if not self.manifest_path.exists():
            return {}
        try:
            value = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AgentSkillRuntimeError("Profile Skill projection manifest is invalid") from exc
        if not isinstance(value, dict) or value.get("schema_version") != RUNTIME_MANIFEST_VERSION:
            raise AgentSkillRuntimeError("unsupported Profile Skill projection version")
        entries = value.get("skills")
        if not isinstance(entries, list):
            raise AgentSkillRuntimeError("Profile Skill projection manifest is invalid")
        result: dict[str, dict[str, str]] = {}
        for entry in entries:
            if not isinstance(entry, dict):
                raise AgentSkillRuntimeError("Profile Skill projection manifest is invalid")
            skill_id = self._text(entry.get("skill_id"), "skill_id")
            name = self._text(entry.get("name"), "Skill name")
            source = self._text(entry.get("source_path"), "Skill path")
            if not SKILL_ID_PATTERN.fullmatch(skill_id) or not SKILL_ID_PATTERN.fullmatch(name):
                raise AgentSkillRuntimeError("Profile Skill projection manifest is invalid")
            binding = {
                "skill_id": skill_id,
                "name": name,
                "source_path": str(Path(source).expanduser().resolve()),
            }
            result[binding["skill_id"]] = binding
        return result

    def selected_bindings(self) -> dict[str, dict[str, str]]:
        """Return the server-owned projection manifest for protocol helpers."""
        return {
            skill_id: dict(binding)
            for skill_id, binding in self._read_manifest().items()
        }

    @staticmethod
    def _link_target(path: Path) -> Path | None:
        if not path.is_symlink():
            return None
        return Path(os.path.realpath(path))

    def _remove_owned_link(
        self,
        skill_id: str,
        previous: dict[str, str],
    ) -> None:
        destination = self.skills_root / skill_id
        if not os.path.lexists(destination):
            return
        expected = Path(previous["source_path"]).expanduser().resolve()
        target = self._link_target(destination)
        if target != expected:
            raise AgentSkillRuntimeError(
                f"refusing to replace an unexpected Skill projection: {destination}"
            )
        destination.unlink()

    def _ensure_link(self, binding: dict[str, str]) -> None:
        destination = self.skills_root / binding["skill_id"]
        source = Path(binding["source_path"])
        if os.path.lexists(destination):
            target = self._link_target(destination)
            if target != source:
                raise AgentSkillRuntimeError(
                    f"refusing to replace an unexpected Skill projection: {destination}"
                )
            return
        os.symlink(source, destination, target_is_directory=True)

    def _write_manifest(self, bindings: list[dict[str, str]]) -> None:
        payload = {
            "schema_version": RUNTIME_MANIFEST_VERSION,
            "skills": [
                {
                    "skill_id": binding["skill_id"],
                    "name": binding["name"],
                    "source_path": binding["source_path"],
                }
                for binding in bindings
            ],
        }
        self.codex_home.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(
            prefix="factortester-skill-projection-",
            suffix=".tmp",
            dir=self.codex_home,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.manifest_path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    @staticmethod
    def _is_codex_system_skills(path: Path) -> bool:
        """Recognize only Codex's own managed system Skill directory.

        Codex creates this directory inside ``CODEX_HOME`` on first launch.
        It is not part of FactorTester's selected Skill projection and must
        not be treated as an unowned user Skill.  The marker check keeps the
        strict collision policy for arbitrary ``.system`` directories.
        """
        return (
            path.name == CODEX_SYSTEM_SKILLS_DIRNAME
            and not path.is_symlink()
            and path.is_dir()
            and (path / CODEX_SYSTEM_SKILLS_MARKER).is_file()
        )

    def sync(self, bindings: list[Mapping[str, object]]) -> dict[str, Any]:
        """Make the Profile projection exactly match the selected bindings."""
        self._prepare_directories()
        normalized: dict[str, dict[str, str]] = {}
        names: set[str] = set()
        for value in bindings:
            binding = self._binding(value)
            if binding["skill_id"] in normalized:
                raise AgentSkillRuntimeError("a Skill is selected more than once")
            if binding["name"] in names:
                raise AgentSkillRuntimeError(
                    f"Skill names must be unique in a Profile: {binding['name']}"
                )
            normalized[binding["skill_id"]] = binding
            names.add(binding["name"])

        previous = self._read_manifest()
        for skill_id, binding in previous.items():
            if skill_id not in normalized:
                self._remove_owned_link(skill_id, binding)
        selected_ids = set(normalized)
        for child in self.skills_root.iterdir():
            if child.name in selected_ids:
                continue
            if self._is_codex_system_skills(child):
                continue
            # Do not delete data that the user or an Agent placed here.  A
            # directory or symlink could be interpreted as another Skill, so
            # refuse to start with it rather than silently widening policy.
            if child.is_symlink() or child.is_dir():
                raise AgentSkillRuntimeError(
                    f"unowned Skill directory is present: {child}"
                )
        for binding in normalized.values():
            self._ensure_link(binding)

        ordered = [normalized[key] for key in sorted(normalized)]
        self._write_manifest(ordered)
        return {
            "workspace_root": str(self.workspace_root),
            "codex_home": str(self.codex_home),
            "skills": [
                {
                    "skill_id": binding["skill_id"],
                    "name": binding["name"],
                    "path": str(
                        self.skills_root / binding["skill_id"] / "SKILL.md"
                    ),
                }
                for binding in ordered
            ],
        }

    def environment(self, base: Mapping[str, str] | None = None) -> dict[str, str]:
        """Return a subprocess environment isolated from the host user's Skills."""
        self._prepare_directories()
        environment = dict(base or os.environ)
        environment.update({
            "CODEX_HOME": str(self.codex_home),
            "HOME": str(self.home_root),
            "XDG_CONFIG_HOME": str(self.config_root),
            "XDG_DATA_HOME": str(self.data_root),
            "XDG_STATE_HOME": str(self.state_root),
        })
        return environment

    @staticmethod
    def command(codex_binary: str = "codex") -> list[str]:
        binary = str(codex_binary or "").strip()
        if not binary:
            raise AgentSkillRuntimeError("codex binary is required")
        return [
            binary,
            "app-server",
            # Server Profiles use FactorTester's explicit, local Skill
            # projection.  Codex's consumer plugin discovery performs remote
            # catalog sync during initialize; a failed sync can outlive the
            # Manager timeout and make the Agent appear to exit empty.
            "--disable",
            "plugins",
            "--disable",
            "remote_plugin",
            "--disable",
            "recommended_plugins",
            "--listen",
            "stdio://",
        ]

    def projected_skill_path(self, skill_id: str) -> Path:
        identifier = self._text(skill_id, "skill_id")
        if not SKILL_ID_PATTERN.fullmatch(identifier):
            raise AgentSkillRuntimeError("Skill id is invalid")
        manifest = self.selected_bindings()
        if identifier not in manifest:
            raise AgentSkillRuntimeError("Skill is not selected for this Profile")
        return self.skills_root / identifier / "SKILL.md"
