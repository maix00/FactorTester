"""Applicability and identity rules for persistent research Evidence."""

from __future__ import annotations

import json
import re
from typing import Any

from tools.cli.factor_subject_refs import validate_factor_subject_ref
from tools.factors.formula_identity import require_frozen_factor

_REF = re.compile(r"^evidence:[a-z_]+:sha256:[0-9a-f]{64}$")

APPLICABILITY_FIELDS = (
    {
        "name": "factor_refs", "section": "objects", "label_zh": "因子候选",
        "type": "string_array", "registration": "factor_execution",
    },
    {
        "name": "factor_set_refs", "section": "objects", "label_zh": "因子集合",
        "type": "string_array", "registration": "factor_execution",
    },
    {
        "name": "factor_source_refs", "section": "objects", "label_zh": "因子来源",
        "type": "string_array", "registration": "factor_execution",
    },
    {
        "name": "product_scope_ref", "section": "objects", "label_zh": "产品范围",
        "type": "reference", "registration": "product_or_group_selection",
        "reuses": ["product_library_product", "product_path_selection"],
        "selection": "single",
    },
    {
        "name": "product_group_refs", "section": "environment", "label_zh": "产品组",
        "type": "string_array", "registration": "product_path_selection",
    },
    {
        "name": "time_window", "section": "environment", "label_zh": "时间范围",
        "type": "time_window", "registration": "time_range",
    },
    {"name": "product_refs", "type": "string_array", "exposed": False},
    {"name": "sample_refs", "type": "string_array", "exposed": False},
    {"name": "factor_subjects", "type": "object_array", "exposed": False},
    {"name": "data_source_refs", "type": "string_array", "exposed": False},
    {"name": "environment_refs", "type": "string_array", "exposed": False},
    {"name": "source_refs", "type": "string_array", "exposed": False},
    {"name": "contract_hash", "type": "sha256", "exposed": False},
    {"name": "methodology_hash", "type": "sha256", "exposed": False},
    {"name": "trial_plan_hash", "type": "sha256", "exposed": False},
    {"name": "run_spec_hash", "type": "sha256", "exposed": False},
    {"name": "limitations", "type": "string_array", "exposed": False},
)


def applicability_schema() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "sections": [
            {"id": "objects", "label_zh": "适用对象"},
            {"id": "environment", "label_zh": "适用环境"},
        ],
        "fields": [dict(field) for field in APPLICABILITY_FIELDS],
    }


def validate_applicability(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("applicability must be an object")
    allowed = {field["name"] for field in APPLICABILITY_FIELDS}
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError("unsupported applicability fields: " + ", ".join(unknown))
    for field in (
        "product_refs", "source_refs", "factor_refs", "factor_set_refs",
        "factor_source_refs", "sample_refs",
        "product_group_refs", "data_source_refs", "environment_refs",
        "limitations",
    ):
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
    if "product_scope_ref" in value:
        text(value["product_scope_ref"], "applicability.product_scope_ref")
    for field in ("contract_hash", "methodology_hash", "trial_plan_hash", "run_spec_hash"):
        if field in value and not sha(value[field]):
            raise ValueError(f"applicability.{field} must be sha256")
    if not any(value.get(field) for field in (
        "product_refs", "source_refs", "factor_refs", "factor_set_refs",
        "factor_source_refs", "sample_refs", "product_scope_ref",
        "product_group_refs", "data_source_refs", "environment_refs",
        "contract_hash", "methodology_hash", "trial_plan_hash", "run_spec_hash",
    )):
        raise ValueError("applicability must declare a non-empty scope")
    if "time_window" in value:
        window = value["time_window"]
        if (
            not isinstance(window, dict)
            or not set(window).issubset({"start", "end"})
            or not set(window)
        ):
            raise ValueError("applicability.time_window is invalid")
        for boundary in ("start", "end"):
            if boundary in window:
                text(window[boundary], f"applicability.time_window.{boundary}")
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
