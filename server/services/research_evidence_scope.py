"""Applicability and identity rules for persistent research Evidence."""

from __future__ import annotations

import json
import re
from typing import Any

from tools.cli.factor_subject_refs import validate_factor_subject_ref
from tools.factors.formula_identity import require_frozen_factor

_REF = re.compile(r"^evidence:[a-z_]+:sha256:[0-9a-f]{64}$")


def validate_applicability(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("applicability must be an object")
    allowed = {
        "product_refs", "source_refs", "factor_refs", "sample_refs",
        "factor_subjects",
        "contract_hash", "methodology_hash", "trial_plan_hash",
        "run_spec_hash", "time_window", "limitations",
    }
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError("unsupported applicability fields: " + ", ".join(unknown))
    for field in ("product_refs", "source_refs", "factor_refs", "sample_refs", "limitations"):
        items = value.get(field, [])
        if not isinstance(items, list) or not all(isinstance(item, str) and item.strip() for item in items):
            raise ValueError(f"applicability.{field} must be a string array")
    for item in value.get("factor_refs", []):
        try:
            validate_factor_subject_ref(item)
        except ValueError as error:
            raise ValueError(
                "applicability.factor_refs contains a non-frozen factor subject"
            ) from error
    subjects = value.get("factor_subjects", [])
    if not isinstance(subjects, list):
        raise ValueError("applicability.factor_subjects must be an array")
    frozen_subjects = []
    for item in subjects:
        try:
            frozen_subjects.append(require_frozen_factor(item))
        except (TypeError, ValueError) as error:
            raise ValueError(
                "applicability.factor_subjects contains an invalid frozen factor"
            ) from error
    subject_refs = [item["ref"] for item in frozen_subjects]
    if len(subject_refs) != len(set(subject_refs)):
        raise ValueError("applicability.factor_subjects must be unique")
    if not set(subject_refs).issubset(set(value.get("factor_refs", []))):
        raise ValueError(
            "applicability.factor_subjects must be declared in factor_refs"
        )
    if frozen_subjects:
        value = {**value, "factor_subjects": frozen_subjects}
    for field in ("contract_hash", "methodology_hash", "trial_plan_hash", "run_spec_hash"):
        if field in value and not sha(value[field]):
            raise ValueError(f"applicability.{field} must be sha256")
    if not any(value.get(field) for field in (
        "product_refs", "source_refs", "factor_refs", "sample_refs",
        "contract_hash", "methodology_hash", "trial_plan_hash", "run_spec_hash",
    )):
        raise ValueError("applicability must declare a non-empty scope")
    if "time_window" in value:
        window = value["time_window"]
        if not isinstance(window, dict) or set(window) != {"start", "end"}:
            raise ValueError("applicability.time_window is invalid")
        text(window["start"], "applicability.time_window.start")
        text(window["end"], "applicability.time_window.end")
    return json.loads(canonical(value))


def check_identity_scope(envelope: dict[str, Any], scope: dict[str, Any]) -> None:
    identity = envelope.get("identity_refs") or {}
    for field in ("contract_hash", "methodology_hash", "trial_plan_hash", "run_spec_hash"):
        if field not in scope:
            continue
        if field not in identity:
            raise ValueError(f"applicability.{field} requires evidence identity")
        left = str(scope[field]).removeprefix("sha256:")
        right = str(identity[field]).removeprefix("sha256:")
        if left != right:
            raise ValueError(f"applicability.{field} does not match evidence identity")


def reference(value: Any) -> str:
    if not isinstance(value, str) or not _REF.fullmatch(value):
        raise ValueError("evidence_ref is invalid")
    return value


def sha(value: Any) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-f]{64}", value.removeprefix("sha256:")))


def text(value: Any, field: str, *, allow_empty: bool = False, maximum: int = 512) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()) or len(value.encode()) > maximum:
        raise ValueError(f"{field} is invalid")
    return value


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
