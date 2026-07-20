"""Persistent local navigation state for the FactorTester CLI."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .http import state_path
from .modules.keys import public_module_key


@dataclass(slots=True)
class CliState:
    current_parent: str | None = None
    stack: list[str | None] = field(default_factory=list)
    workspace_id: str = ""
    configuration_revision: int = 0

    @property
    def location_label(self) -> str:
        if self.current_parent is None:
            return "首页"
        if self.current_parent == "single_factor_family_test":
            return "因子研究"
        return public_module_key(self.current_parent)

    def enter(self, parent: str) -> None:
        if self.current_parent == parent:
            return
        self.stack.append(self.current_parent)
        self.current_parent = parent

    def back(self) -> bool:
        if not self.stack:
            self.current_parent = None
            return False
        self.current_parent = self.stack.pop()
        return True

    def reset(self) -> None:
        self.current_parent = None
        self.stack.clear()


def load_state(path: Path | None = None) -> CliState:
    target = path or state_path()
    if not target.exists():
        return CliState()
    raw = json.loads(target.read_text(encoding="utf-8"))
    return CliState(
        current_parent=raw.get("current_parent"),
        stack=list(raw.get("stack") or []),
        workspace_id=str(raw.get("workspace_id") or ""),
        configuration_revision=int(raw.get("configuration_revision") or 0),
    )


def save_state(state: CliState, path: Path | None = None) -> None:
    target = path or state_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(_state_payload(state), ensure_ascii=False, indent=2), encoding="utf-8")


def _state_payload(state: CliState) -> dict[str, Any]:
    payload = asdict(state)
    payload["stack"] = list(state.stack)
    return payload
