"""Content-addressed local detail objects for lazy report inspection."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any

import orjson

from .generation import publish_generation


def stage_run_spec_preview(
    *,
    package_root: Path,
    branch_id: str,
    presentation: dict[str, Any],
) -> Path:
    """Persist one source-free preview outside the server database."""
    value = deepcopy(presentation)
    if value.get("schema_version") != 1:
        raise ValueError("RunSpec presentation schema is invalid")
    if value.get("object_kind") != "run_spec":
        raise ValueError("RunSpec presentation kind is invalid")
    run_spec = value.get("complete_parameters")
    if not isinstance(run_spec, dict):
        raise ValueError("RunSpec presentation has no complete parameters")
    expected = hashlib.sha256(orjson.dumps(
        run_spec, option=orjson.OPT_SORT_KEYS,
    )).hexdigest()
    actual = str(value.get("run_spec_hash") or "").removeprefix("sha256:")
    if actual != expected:
        raise ValueError("RunSpec presentation hash does not match parameters")
    value["run_spec_hash"] = actual
    value["complete_parameters_json"] = json.dumps(
        run_spec, ensure_ascii=False, indent=2, sort_keys=True,
    )
    payload = json.dumps(
        value, ensure_ascii=False, indent=2, sort_keys=True,
    ).encode("utf-8") + b"\n"
    if len(payload) > 2 * 1024 * 1024:
        raise ValueError("RunSpec presentation exceeds local object limit")
    target = (
        Path(package_root) / "branches" / branch_id / "objects"
        / "run_spec" / f"{actual}.json"
    )
    publish_generation([("run_spec_preview", target, payload)])
    return target
