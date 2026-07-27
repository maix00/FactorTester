"""Load source-only Strategy Actors for one immutable Run payload."""

from __future__ import annotations

import types
from pathlib import PurePosixPath
from typing import Any

from tools.testers.backtest.engines.native.strategy import Strategy


def strategy_objects_from_payload(payload: dict[str, Any]) -> dict[str, Strategy]:
    objects: dict[str, Strategy] = {}
    for raw in payload.get("strategy_specs") or []:
        if not isinstance(raw, dict):
            raise ValueError("strategy spec must be an object")
        source = str(raw.get("source") or "")
        strategy_id = str(raw.get("strategy_id") or "").strip()
        if source.startswith("builtin:"):
            continue
        if not source.startswith(("profile:", "personal:")):
            raise ValueError("strategy source must use builtin, profile, or personal")
        relative = source.split(":", 1)[1]
        path = PurePosixPath(relative)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("strategy source path escapes its workspace")
        scope_id = str(payload.get("transient_strategy_source_scope_id") or "")
        owner = str(payload.get("_owner") or "")
        from server.services.transient_strategy_sources import load_source

        source_code = load_source(scope_id, relative, owner=owner)
        if source_code is None:
            raise ValueError(
                f"strategy source unavailable for this Run: {relative}; "
                "submit the Profile strategy-worktree with the Run"
            )
        module = types.ModuleType(f"factortester_strategy_{len(objects)}")
        module.__file__ = relative
        exec(compile(source_code, relative, "exec"), module.__dict__)
        entrypoint = str(raw.get("entrypoint") or "Strategy")
        actor = getattr(module, entrypoint, None)
        if not isinstance(actor, type) or not issubclass(actor, Strategy):
            raise ValueError(f"strategy entrypoint is not a native Strategy: {entrypoint}")
        alias = strategy_id or path.stem
        objects[alias] = actor(alias=alias)
    return objects

