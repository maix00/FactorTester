"""Migrate saved template snapshots from the legacy top-level ``params_list``
field to ``factor_candidates`` (+ ``factor``), the shape used by the factors
tab / window.Panels (panel_registry.js).

Each legacy params entry (a bare param dict) becomes a candidate:

    {"alias": <factor_alias>, "in_library": bool,
     "library_product_group": <group name or None>, "params": {...}}

``alias`` and the library cross-reference cannot be computed from the snapshot
alone — they need the factor family instance and the user's factor library — so
the caller passes a ``resolve`` callback:

    resolve(params: dict) -> {"alias": str, "in_library": bool,
                              "library_product_group": str | None}
"""

from __future__ import annotations

from typing import Any, Callable


def migrate_snapshot_to_factor_candidates(
    snapshot: dict[str, Any],
    resolve: Callable[[dict], dict],
) -> tuple[dict[str, Any], bool]:
    """Return (snapshot, changed) with legacy params_list converted to factor_candidates."""
    if not isinstance(snapshot, dict):
        return snapshot, False
    legacy = snapshot.get("params_list")
    if not isinstance(legacy, list):
        return snapshot, False

    migrated = dict(snapshot)
    del migrated["params_list"]
    if "factor_candidates" not in migrated:
        candidates = []
        for params in legacy:
            if not isinstance(params, dict):
                continue
            meta = resolve(params) or {}
            group = meta.get("library_product_group")
            candidates.append({
                "alias": meta.get("alias", ""),
                "in_library": bool(meta.get("in_library", False)),
                "library_product_group": group if group else None,
                "params": {k: v for k, v in params.items()},
            })
        migrated["factor_candidates"] = candidates
        if "factor" not in migrated:
            migrated["factor"] = candidates[0]["alias"] if candidates else ""
    return migrated, True
