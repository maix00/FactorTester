"""Validation helpers for fragment-bound reusable research Evidence."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

SOURCE_KINDS = frozenset({"job", "terminal", "file", "web"})
EVIDENCE_KINDS = frozenset({
    "hypothesis_semantics",
    "data_availability",
    "data_contract",
    "factor_semantics",
    "trial_diagnostics",
    "authoritative_backtest",
    "statistical_robustness",
})
_CONTRACT_KINDS = frozenset({
    "hypothesis_semantics",
    "data_availability",
    "data_contract",
    "factor_semantics",
})
_RUN_KINDS = EVIDENCE_KINDS - _CONTRACT_KINDS
_HAN = re.compile(r"[\u3400-\u9fff]")
_SAFE_PROFILE = re.compile(r"^profile:[A-Za-z0-9._-]+$")
_SOURCE_REF = re.compile(
    r"^source:(job|terminal|file|web):sha256:[0-9a-f]{64}$"
)
_FRAGMENT_REF = re.compile(
    r"^fragment:(job|terminal|file|web):sha256:[0-9a-f]{64}$"
)


def canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def sha256(value: Any, field: str) -> str:
    text = str(value or "").removeprefix("sha256:")
    if not re.fullmatch(r"[0-9a-f]{64}", text):
        raise ValueError(f"{field} must be sha256")
    return text


def required_text(
    value: Any,
    field: str,
    *,
    maximum: int = 512,
    chinese: bool = False,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    text = value.strip()
    if len(text) > maximum:
        raise ValueError(f"{field} exceeds {maximum} characters")
    if chinese and _HAN.search(text) is None:
        raise ValueError(f"{field} must contain Chinese display text")
    return text


def source_kind(value: Any) -> str:
    text = required_text(value, "source_kind", maximum=32)
    if text not in SOURCE_KINDS:
        raise ValueError("unsupported source_kind")
    return text


def evidence_kind(value: Any) -> str:
    text = required_text(value, "evidence_kind", maximum=64)
    if text in {"job_attempt", "control_command"}:
        raise ValueError(
            "job_attempt/control_command are source kinds, not evidence kinds"
        )
    if text not in EVIDENCE_KINDS:
        raise ValueError("unsupported evidence_kind")
    return text


def source_reference(value: Any) -> str:
    text = required_text(value, "source_ref", maximum=128)
    if _SOURCE_REF.fullmatch(text) is None:
        raise ValueError("source_ref is invalid")
    return text


def fragment_reference(value: Any) -> str:
    text = required_text(value, "fragment_ref", maximum=128)
    if _FRAGMENT_REF.fullmatch(text) is None:
        raise ValueError("fragment_ref is invalid")
    return text


def profile_reference(value: Any) -> str:
    text = required_text(value, "created_by_profile_ref", maximum=128)
    if _SAFE_PROFILE.fullmatch(text) is None:
        raise ValueError("created_by_profile_ref is invalid")
    return text


def object_value(value: Any, field: str, *, allow_empty: bool = False) -> dict:
    if not isinstance(value, dict) or (not allow_empty and not value):
        raise ValueError(f"{field} must be an object")
    canonical(value)
    return json.loads(canonical(value))


def text_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise ValueError(f"{field} must be a text array")
    return list(dict.fromkeys(item.strip() for item in value))


def validate_identity(evidence: str, identity: Any) -> dict[str, str]:
    value = object_value(identity, "identity_refs")
    allowed = {
        "contract_hash",
        "methodology_hash",
        "trial_plan_hash",
        "run_spec_hash",
    }
    if set(value) - allowed:
        raise ValueError("identity_refs contains unsupported fields")
    normalized = {
        field: sha256(item, f"identity_refs.{field}")
        for field, item in value.items()
    }
    required = (
        ("contract_hash", "methodology_hash")
        if evidence in _CONTRACT_KINDS
        else (
            "contract_hash",
            "methodology_hash",
            "trial_plan_hash",
            "run_spec_hash",
        )
    )
    missing = [field for field in required if field not in normalized]
    if missing:
        raise ValueError(
            f"{evidence} evidence requires " + ", ".join(missing)
        )
    return normalized


def validate_selector(kind: str, value: Any) -> dict:
    selector = object_value(value, "selector")
    allowed = {
        "job": {
            "json_pointer", "metric_ref", "artifact_ref", "event_ref",
            "time_range", "row_key", "field",
        },
        "terminal": {
            "stream", "line_range", "json_pointer", "return_code",
        },
        "file": {
            "line_range", "heading", "page", "cell", "symbol", "byte_range",
        },
        "web": {
            "heading", "anchor", "selector", "quote_hash", "text_range",
        },
    }[kind]
    unknown = sorted(set(selector) - allowed)
    if unknown:
        raise ValueError(
            f"selector contains unsupported {kind} fields: "
            + ", ".join(unknown)
        )
    return selector
