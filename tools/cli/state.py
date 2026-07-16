"""Persistent local navigation state for the FactorTester CLI."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .http import state_path
from .modules.keys import public_module_key

BACKTEST_SPACE = "backtest"
SINGLE_FACTOR_BACKTEST_SPACE = "single_factor_test"


@dataclass(slots=True)
class CliState:
    current_parent: str | None = None
    stack: list[str | None] = field(default_factory=list)
    factor_family: str = ""
    workspace_id: str = ""
    workspace_revision: int = 0
    page_settings: dict[str, Any] = field(default_factory=dict)
    active_backtest_space: str = BACKTEST_SPACE
    backtest_spaces: dict[str, dict[str, Any]] = field(default_factory=dict)
    backtest_local_settings: dict[str, Any] = field(default_factory=dict)
    backtest_strategy_book: dict[str, Any] = field(default_factory=dict)
    backtest_ledger_configs: dict[str, dict[str, Any]] = field(default_factory=dict)
    backtest_groups: list[dict[str, Any]] = field(default_factory=list)
    backtest_ls_configs: list[dict[str, Any]] = field(default_factory=list)
    backtest_last_result: dict[str, Any] = field(default_factory=dict)
    ic_test_local_settings: dict[str, Any] = field(default_factory=dict)
    ic_test_configs: list[dict[str, Any]] = field(default_factory=list)
    factor_evaluation_local_settings: dict[str, Any] = field(default_factory=dict)
    factor_type_analysis_local_settings: dict[str, Any] = field(default_factory=dict)

    @property
    def location_label(self) -> str:
        if self.current_parent is None:
            return "首页"
        if self.current_parent == "single_factor_family_test":
            suffix = f" · {self.factor_family}" if self.factor_family else ""
            return f"单因子家族测试{suffix}"
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
    legacy_space = {
        "local_settings": dict(raw.get("backtest_local_settings") or {}),
        "groups": list(raw.get("backtest_groups") or []),
        "ls_configs": list(raw.get("backtest_ls_configs") or []),
    }
    spaces = dict(raw.get("backtest_spaces") or {})
    if not spaces and any(legacy_space.values()):
        spaces[BACKTEST_SPACE] = legacy_space
    state = CliState(
        current_parent=raw.get("current_parent"),
        stack=list(raw.get("stack") or []),
        factor_family=str(raw.get("factor_family") or ""),
        workspace_id=str(raw.get("workspace_id") or ""),
        workspace_revision=int(raw.get("workspace_revision") or 0),
        page_settings=dict(raw.get("page_settings") or {}),
        active_backtest_space=str(raw.get("active_backtest_space") or BACKTEST_SPACE),
        backtest_spaces=spaces,
        backtest_local_settings=dict(raw.get("backtest_local_settings") or {}),
        backtest_strategy_book=dict(raw.get("backtest_strategy_book") or {}),
        backtest_ledger_configs={
            str(key): dict(value)
            for key, value in (raw.get("backtest_ledger_configs") or {}).items()
            if isinstance(value, dict)
        },
        backtest_groups=list(raw.get("backtest_groups") or []),
        backtest_ls_configs=list(raw.get("backtest_ls_configs") or []),
        backtest_last_result=dict(raw.get("backtest_last_result") or {}),
        ic_test_local_settings=dict(raw.get("ic_test_local_settings") or {}),
        ic_test_configs=list(raw.get("ic_test_configs") or []),
        factor_evaluation_local_settings=dict(raw.get("factor_evaluation_local_settings") or {}),
        factor_type_analysis_local_settings=dict(raw.get("factor_type_analysis_local_settings") or {}),
    )
    load_backtest_space_into_legacy_fields(state, state.active_backtest_space)
    return state


def save_state(state: CliState, path: Path | None = None) -> None:
    target = path or state_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(_state_payload(state), ensure_ascii=False, indent=2), encoding="utf-8")


def _state_payload(state: CliState) -> dict[str, Any]:
    sync_active_backtest_space(state)
    payload = asdict(state)
    payload["stack"] = list(state.stack)
    return payload


def switch_backtest_space(state: CliState, space: str) -> None:
    """Switch the mutable legacy backtest fields to a named draft scope."""
    current = state.active_backtest_space or BACKTEST_SPACE
    sync_active_backtest_space(state, space=current)
    state.active_backtest_space = space or BACKTEST_SPACE
    load_backtest_space_into_legacy_fields(state, state.active_backtest_space)


def sync_active_backtest_space(state: CliState, *, space: str | None = None) -> None:
    target = space or state.active_backtest_space or BACKTEST_SPACE
    state.backtest_spaces[target] = {
        "local_settings": dict(state.backtest_local_settings),
        "strategy_book": dict(state.backtest_strategy_book),
        "ledger_configs": {
            str(key): dict(value)
            for key, value in state.backtest_ledger_configs.items()
        },
        "groups": [dict(group) for group in state.backtest_groups],
        "ls_configs": [dict(config) for config in state.backtest_ls_configs],
    }


def load_backtest_space_into_legacy_fields(state: CliState, space: str) -> None:
    data = state.backtest_spaces.get(space) or {}
    state.backtest_local_settings = dict(data.get("local_settings") or {})
    state.backtest_strategy_book = dict(data.get("strategy_book") or {})
    state.backtest_ledger_configs = {
        str(key): dict(value)
        for key, value in (data.get("ledger_configs") or {}).items()
        if isinstance(value, dict)
    }
    state.backtest_groups = [dict(group) for group in (data.get("groups") or []) if isinstance(group, dict)]
    state.backtest_ls_configs = [dict(config) for config in (data.get("ls_configs") or []) if isinstance(config, dict)]
