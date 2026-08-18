"""Server-installed Agent Skill catalog and Profile selection helpers.

The catalog is an explicit allowlist.  Files that merely happen to exist in a
repository Skill directory are not exposed to user Profiles unless they are
listed in the server-owned manifest.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

SKILL_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


class AgentSkillCatalogError(ValueError):
    """The server Skill catalog is invalid or unavailable."""


def _frontmatter_value(skill_path: Path, key: str) -> str:
    """Read one scalar frontmatter value without adding a YAML dependency."""
    try:
        lines = skill_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise AgentSkillCatalogError("installed Skill metadata is unavailable") from exc
    if not lines or lines[0].strip() != "---":
        return ""
    for line in lines[1:]:
        if line.strip() == "---":
            break
        name, separator, value = line.partition(":")
        if separator and name.strip() == key:
            return value.strip().strip("\"'")
    return ""


class AgentSkillCatalog:
    """Read the immutable, server-installed Skill allowlist."""

    def __init__(self, source_root: str | Path, manifest_path: str | Path) -> None:
        self.source_root = Path(source_root).expanduser().resolve()
        self.manifest_path = Path(manifest_path).expanduser().resolve()

    def _manifest(self) -> list[dict[str, Any]]:
        try:
            value = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise AgentSkillCatalogError("server Skill catalog is unavailable") from exc
        except json.JSONDecodeError as exc:
            raise AgentSkillCatalogError("server Skill catalog is invalid") from exc
        if not isinstance(value, dict) or value.get("schema_version") != 1:
            raise AgentSkillCatalogError("unsupported server Skill catalog version")
        skills = value.get("skills")
        if not isinstance(skills, list):
            raise AgentSkillCatalogError("server Skill catalog has no skills list")
        return [item for item in skills if isinstance(item, dict)]

    def _skill_path(self, relative_path: str) -> Path:
        relative = Path(str(relative_path or "").strip())
        if not relative or relative.is_absolute() or ".." in relative.parts:
            raise AgentSkillCatalogError("Skill path must stay inside the server source root")
        path = (self.source_root / relative).resolve()
        try:
            path.relative_to(self.source_root)
        except ValueError as exc:
            raise AgentSkillCatalogError("Skill path escapes the server source root") from exc
        if not path.is_dir() or not (path / "SKILL.md").is_file():
            raise AgentSkillCatalogError(f"installed Skill is missing: {relative}")
        return path

    @staticmethod
    def _runtime_kinds(item: dict[str, Any]) -> tuple[str, ...]:
        raw = item.get("runtime_kinds")
        if raw is None:
            raw = ["server"]
        if not isinstance(raw, list):
            raise AgentSkillCatalogError("Skill runtime_kinds must be a list")
        values = tuple(str(value).strip() for value in raw if str(value).strip())
        if not values or any(value not in {"client", "server"} for value in values):
            raise AgentSkillCatalogError("Skill runtime_kinds is unsupported")
        return values

    def _definition(self, item: dict[str, Any]) -> dict[str, Any] | None:
        skill_id = str(item.get("id") or "").strip()
        if not SKILL_ID_PATTERN.fullmatch(skill_id):
            raise AgentSkillCatalogError("Skill id is invalid")
        # manager_only entries are intentionally not user-selectable.  They
        # remain installable for Manager maintenance without becoming Agent
        # instructions or capabilities.
        if str(item.get("audience") or "profile").strip() != "profile":
            return None
        if item.get("enabled", True) is False:
            return None
        relative_path = str(item.get("path") or "").strip()
        path = self._skill_path(relative_path)
        runtimes = self._runtime_kinds(item)
        label = str(item.get("label") or skill_id).strip()
        description = str(item.get("description") or "").strip()
        version = str(item.get("version") or "").strip()
        skill_name = _frontmatter_value(path / "SKILL.md", "name") or skill_id
        if not SKILL_ID_PATTERN.fullmatch(skill_name):
            raise AgentSkillCatalogError(f"installed Skill name is invalid: {skill_name}")
        return {
            "skill_id": skill_id,
            "name": skill_name,
            "label": label,
            "description": description,
            "version": version,
            "runtime_kinds": list(runtimes),
            "relative_path": relative_path,
            "path": str(path),
        }

    def definitions(self, runtime_kind: str = "server") -> list[dict[str, Any]]:
        runtime = str(runtime_kind or "").strip()
        if runtime not in {"client", "server"}:
            raise AgentSkillCatalogError("runtime_kind is unsupported")
        result: list[dict[str, Any]] = []
        for item in self._manifest():
            definition = self._definition(item)
            if definition and runtime in definition["runtime_kinds"]:
                result.append(definition)
        return sorted(result, key=lambda item: (item["label"].casefold(), item["skill_id"]))

    def public_definitions(self, runtime_kind: str = "server") -> list[dict[str, Any]]:
        """Return metadata safe for the browser; never disclose local paths."""
        return [
            {
                key: value
                for key, value in item.items()
                if key not in {"path", "relative_path"}
            }
            for item in self.definitions(runtime_kind)
        ]
