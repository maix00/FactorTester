"""Lossless schema-v1 frame upgrade into the canonical v2 stack."""

from __future__ import annotations

from copy import deepcopy
import hashlib
from typing import Any

import orjson


def upgrade_legacy_frame(
    value: dict[str, Any],
) -> dict[str, Any] | None:
    target = str(value.get("resume_node") or "")
    if not target:
        return None
    payload = {key: item for key, item in value.items() if key != "frame_id"}
    digest = hashlib.sha256(
        orjson.dumps(payload, option=orjson.OPT_SORT_KEYS)
    ).hexdigest()
    unresolved = _ids(value.get("unresolved_requirement_ids"))
    resolved = _ids(value.get("resolved_requirement_ids"))
    return {
        "schema_version": 2,
        "entry_attempt_id": f"legacy-entry-{digest}",
        "target_node": target,
        "entry_requirement_refs": sorted(set(unresolved + resolved)),
        "unresolved_entry_requirement_refs": unresolved,
        "resolved_entry_requirement_refs": resolved,
        "status": (
            "resolved" if value.get("status") == "resolved" else "resolving"
        ),
        "legacy_projection": {
            key: deepcopy(item)
            for key, item in value.items()
            if key not in {"assessment_receipts", "schema_version"}
        },
    }


def _ids(value: Any) -> list[str]:
    return sorted({str(item) for item in value or [] if str(item)})
