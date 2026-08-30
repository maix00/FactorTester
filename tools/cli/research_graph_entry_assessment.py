"""Entry-assessment authoring managed by ``research graphs node advance``."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import Any

from cli_anything.factortester_research.core.entry_preparation import (
    build_entry_assessment_skeleton,
    compact_factor_facts,
    validate_entry_assessment_document,
)
from cli_anything.factortester_research.utils.factortester_backend import (
    run_factortester,
)


def prepare_entry_assessment(
    *,
    next_packet: dict[str, Any],
    factor_family: str,
    factor_source: str,
    output: Path,
) -> dict[str, Any]:
    """Write an editable document for every active Entry Requirement."""
    requirement_ids = list(dict.fromkeys(
        str(item.get("requirement_id") or "")
        for item in next_packet.get("entry_requirements") or []
        if isinstance(item, dict) and item.get("requirement_id")
    ))
    if not requirement_ids:
        raise ValueError("the current node has no active Entry Requirements")
    details = {
        requirement_id: _call_json([
            "research",
            "graphs",
            "requirement-detail",
            str((next_packet.get("branch") or {}).get("instance_id") or ""),
            str((next_packet.get("branch") or {}).get("branch_id") or ""),
            requirement_id,
        ])
        for requirement_id in requirement_ids
    }
    describe = _call_json([
        "factor-library",
        "describe",
        factor_family,
        "--source",
        factor_source,
        "--debug-graph",
        "--json",
    ])
    document = build_entry_assessment_skeleton(
        next_packet=next_packet,
        requirement_details=details,
        factor_facts=compact_factor_facts(
            describe,
            factor_ref=factor_family,
        ),
        selected_requirement_ids=requirement_ids,
    )
    _atomic_json(output, document)
    return document


def normalize_entry_assessment(value: dict[str, Any]) -> dict[str, Any]:
    """Accept an editable document or an already normalized projection."""
    if isinstance(value.get("entry_requirement_assessments"), list):
        return value
    return validate_entry_assessment_document(value)


def _call_json(args: list[str]) -> dict[str, Any]:
    result = run_factortester(args, timeout=60)
    if result.returncode != 0:
        raise ValueError(
            (result.stderr or result.stdout or "FactorTester command failed")[
                :1000
            ]
        )
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("FactorTester returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("FactorTester JSON must be an object")
    return value


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
