"""Generic RunSpec control-pair validation for activation fixtures."""

from __future__ import annotations

from typing import Any


def validate_control_pairs(
    pairs: Any,
    summaries: Any,
) -> list[str]:
    if not isinstance(pairs, list) or not pairs:
        raise ValueError("validation_contract.control_pairs must be non-empty")
    if not isinstance(summaries, dict):
        raise ValueError("run_spec_summaries must be an object")
    pair_ids: list[str] = []
    for pair in pairs:
        if not isinstance(pair, dict):
            raise ValueError("control pair must be an object")
        pair_id = _text(pair, "pair_id")
        baseline = _summary(
            summaries,
            _text(pair, "baseline_run_hash"),
        )
        target = _summary(
            summaries,
            _text(pair, "target_run_hash"),
        )
        invariant = _text_list(pair, "invariant_fields")
        differences = _text_list(
            pair,
            "allowed_difference_fields",
            allow_empty=True,
        )
        overlap = set(invariant).intersection(differences)
        if overlap:
            raise ValueError(
                f"{pair_id} repeats fields across invariant/difference sets"
            )
        if any(baseline.get(field) != target.get(field) for field in invariant):
            raise ValueError(
                f"{pair_id} must preserve declared invariant control fields"
            )
        actual_differences = {
            field
            for field in differences
            if baseline.get(field) != target.get(field)
        }
        if actual_differences != set(differences):
            raise ValueError(
                f"{pair_id} must change exactly its allowed difference fields"
            )
        pair_ids.append(pair_id)
    if len(pair_ids) != len(set(pair_ids)):
        raise ValueError("control pair IDs must be unique")
    return pair_ids


def _summary(summaries: dict[str, Any], run_hash: str) -> dict[str, Any]:
    value = summaries.get(run_hash)
    if not isinstance(value, dict):
        raise ValueError(f"missing RunSpec summary: {run_hash}")
    return value


def _text(value: dict[str, Any], field: str) -> str:
    result = value.get(field)
    if not isinstance(result, str) or not result:
        raise ValueError(f"{field} must be non-empty text")
    return result


def _text_list(
    value: dict[str, Any],
    field: str,
    *,
    allow_empty: bool = False,
) -> list[str]:
    result = value.get(field)
    if (
        not isinstance(result, list)
        or (not allow_empty and not result)
        or not all(isinstance(item, str) and item for item in result)
    ):
        raise ValueError(f"{field} must be a text array")
    return result
