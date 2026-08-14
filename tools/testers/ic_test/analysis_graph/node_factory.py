"""Canonical construction for content-addressed IC analysis nodes."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from .model import ICAnalysisNode


def analysis_node(
    analysis_type: str,
    target_refs: tuple[str, ...],
    parameters: Mapping[str, Any],
) -> ICAnalysisNode:
    identity = {
        "analysis_type": analysis_type,
        "target_refs": sorted(target_refs),
        "parameters": parameters,
    }
    encoded = json.dumps(
        identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode()
    return ICAnalysisNode(
        node_id=f"ic-analysis:v1:{hashlib.sha256(encoded).hexdigest()}",
        analysis_type=analysis_type,
        target_refs=tuple(sorted(target_refs)),
        parameters=parameters,
    )


__all__ = ["analysis_node"]
