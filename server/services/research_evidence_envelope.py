"""Factual evidence protocol and legacy Agent-access boundary."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import re
from typing import Any

import orjson


_INTERPRETATION_FIELDS = {
    "adjudication",
    "claim_evidence_delta",
    "conclusion",
    "decision",
    "decision_warrant",
}
_IDENTITY_HASH_FIELDS = {
    "contract_hash",
    "methodology_hash",
    "run_spec_hash",
    "sample_use_hash",
    "trial_plan_hash",
}
_CONTRACT_EVIDENCE_KINDS = frozenset({
    "hypothesis_semantics",
    "data_availability",
    "data_contract",
    "factor_semantics",
})
_RUN_EVIDENCE_KINDS = frozenset({
    "trial_diagnostics",
    "authoritative_backtest",
    "statistical_robustness",
    "job_attempt",
})
_HAN = re.compile(r"[\u3400-\u9fff]")


class LegacyEvidenceAccessDenied(ValueError):
    """Raised when an Agent-facing surface receives legacy evidence."""


MAX_EVIDENCE_ENVELOPE_BYTES = 96 * 1024


def json_hash(value: Any) -> str:
    return hashlib.sha256(
        orjson.dumps(value, option=orjson.OPT_SORT_KEYS)
    ).hexdigest()


def assert_no_skill_identity(value: Any, *, location: str) -> None:
    forbidden_fields = {
        "skill_name", "implementation_id", "provider", "source_path",
        "source_fingerprint", "loaded_skill_ids", "loaded_skill_receipts",
    }
    if isinstance(value, dict):
        forbidden = sorted(str(key) for key in value if str(key) in forbidden_fields)
        if forbidden:
            raise ValueError(
                f"{location} may persist descriptions, not Skill identity: "
                + ", ".join(forbidden)
            )
        for item in value.values():
            assert_no_skill_identity(item, location=location)
    elif isinstance(value, list):
        for item in value:
            assert_no_skill_identity(item, location=location)


def _serialize_bounded_evidence(evidence: dict[str, Any]) -> str:
    serialized = orjson.dumps(evidence, option=orjson.OPT_SORT_KEYS)
    if len(serialized) > MAX_EVIDENCE_ENVELOPE_BYTES:
        raise ValueError(
            "evidence envelope exceeds "
            f"{MAX_EVIDENCE_ENVELOPE_BYTES} bytes: {len(serialized)}"
        )
    return serialized.decode()


def _required_text(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value


def _sha256(value: Any, *, field: str) -> str:
    text = _required_text(value, field=field).removeprefix("sha256:")
    if len(text) != 64 or any(
        character not in "0123456789abcdef" for character in text
    ):
        raise ValueError(f"{field} must be sha256")
    return text


def legacy_evidence_metadata(envelope: dict[str, Any]) -> dict[str, Any]:
    """Return the only legacy fields allowed across compatibility code."""
    if not isinstance(envelope, dict) or envelope.get("schema_version") != 1:
        raise ValueError("legacy evidence schema_version must be 1")
    return {
        "schema_version": 1,
        "envelope_id": _required_text(
            envelope.get("envelope_id"),
            field="envelope_id",
        ),
        "envelope_hash": _sha256(
            envelope.get("envelope_hash"),
            field="envelope_hash",
        ),
        "eligibility": "legacy_ineligible",
    }


def assert_no_legacy_evidence_payload(value: Any) -> None:
    """Reject legacy envelopes anywhere in an Agent-submitted payload."""
    if isinstance(value, dict):
        if _looks_like_legacy_envelope(value):
            raise LegacyEvidenceAccessDenied(
                "legacy evidence is unavailable to Agents"
            )
        for item in value.values():
            assert_no_legacy_evidence_payload(item)
    elif isinstance(value, list):
        for item in value:
            assert_no_legacy_evidence_payload(item)


def validate_agent_evidence_payload(value: Any) -> Any:
    """Validate and canonicalize embedded envelopes before persistence."""
    assert_no_legacy_evidence_payload(value)
    return _validate_current_envelopes(value)


def _validate_current_envelopes(value: Any) -> Any:
    if isinstance(value, dict):
        if _looks_like_current_envelope(value):
            return validate_agent_evidence_envelope(value)
        return {
            str(key): _validate_current_envelopes(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_validate_current_envelopes(item) for item in value]
    return deepcopy(value)


def validate_agent_evidence_envelope(
    envelope: dict[str, Any],
) -> dict[str, Any]:
    """Validate current evidence while denying legacy Agent access."""
    if not isinstance(envelope, dict):
        raise ValueError("evidence envelope must be an object")
    if envelope.get("schema_version") == 1:
        raise LegacyEvidenceAccessDenied(
            "legacy evidence is unavailable to Agents"
        )
    if envelope.get("schema_version") != 2:
        raise ValueError("evidence schema_version must be 2")
    assert_no_skill_identity(envelope, location="evidence envelope")
    value = deepcopy(envelope)
    declared_hash = value.pop("envelope_hash", "")
    forbidden = sorted(_find_fields(value, _INTERPRETATION_FIELDS))
    if forbidden:
        raise ValueError(
            "factual evidence must not contain decision fields: "
            + ", ".join(forbidden)
        )
    _required_text(value.get("envelope_id"), field="envelope_id")
    evidence_kind = _required_text(
        value.get("evidence_kind"),
        field="evidence_kind",
    )
    for field, maximum in (("title", 160), ("claim_summary", 240)):
        text = value.get(field)
        if text is None:
            continue
        normalized = _required_text(text, field=field).strip()
        if len(normalized.encode()) > maximum:
            raise ValueError(f"{field} exceeds {maximum} bytes")
        if _HAN.search(normalized) is None:
            raise ValueError(f"{field} must contain Chinese display text")
        value[field] = normalized
    _references(value.get("source_refs"), field="source_refs", required=True)
    identity_refs = value.get("identity_refs")
    if not isinstance(identity_refs, dict):
        raise ValueError("identity_refs must be an object")
    unsupported_identity_fields = sorted(
        set(identity_refs) - _IDENTITY_HASH_FIELDS
    )
    if unsupported_identity_fields:
        raise ValueError(
            "identity_refs contains unsupported fields: "
            + ", ".join(unsupported_identity_fields)
        )
    for field in _IDENTITY_HASH_FIELDS:
        if field in identity_refs:
            _sha256(identity_refs[field], field=f"identity_refs.{field}")
    _validate_research_identity(
        evidence_kind=evidence_kind,
        identity_refs=identity_refs,
    )
    command = value.get("command")
    if command is not None:
        _command(command)
    for field in ("metric_refs", "artifact_refs"):
        _references(value.get(field), field=field)
    hypotheses_tested = value.get("hypotheses_tested")
    if (
        not isinstance(hypotheses_tested, int)
        or isinstance(hypotheses_tested, bool)
        or hypotheses_tested < 0
    ):
        raise ValueError("hypotheses_tested must be non-negative")
    stop_condition = value.get("stop_condition")
    if stop_condition is not None and not isinstance(stop_condition, str):
        raise ValueError("stop_condition must be a string or null")
    for field in ("limitations", "conflicts"):
        _text_list(value.get(field), field=field)
    computed_hash = json_hash(value)
    if declared_hash and _sha256(
        declared_hash,
        field="envelope_hash",
    ) != computed_hash:
        raise ValueError("envelope_hash mismatch")
    value["envelope_hash"] = computed_hash
    _serialize_bounded_evidence(value)
    return value


def _validate_research_identity(
    *,
    evidence_kind: str,
    identity_refs: dict[str, Any],
) -> None:
    if evidence_kind in _CONTRACT_EVIDENCE_KINDS:
        required = ("contract_hash", "methodology_hash")
    elif evidence_kind in _RUN_EVIDENCE_KINDS:
        required = (
            "contract_hash",
            "methodology_hash",
            "run_spec_hash",
        )
    else:
        raise ValueError(
            f"unsupported research evidence_kind: {evidence_kind}"
        )
    for field in required:
        if field not in identity_refs:
            raise ValueError(
                f"{evidence_kind} evidence requires identity_refs.{field}"
            )


def _looks_like_legacy_envelope(value: dict[str, Any]) -> bool:
    return (
        value.get("schema_version") == 1
        and isinstance(value.get("envelope_id"), str)
    )


def _looks_like_current_envelope(value: dict[str, Any]) -> bool:
    return (
        value.get("schema_version") == 2
        and isinstance(value.get("envelope_id"), str)
        and isinstance(value.get("evidence_kind"), str)
    )


def _find_fields(value: Any, forbidden: set[str]) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key) in forbidden:
                found.add(str(key))
            found.update(_find_fields(item, forbidden))
    elif isinstance(value, list):
        for item in value:
            found.update(_find_fields(item, forbidden))
    return found


def _references(
    value: Any,
    *,
    field: str,
    required: bool = False,
) -> list[str]:
    if not isinstance(value, list) or (
        required and not value
    ) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        qualifier = "non-empty " if required else ""
        raise ValueError(f"{field} must be a {qualifier}reference array")
    return value


def _text_list(value: Any, *, field: str) -> list[str]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise ValueError(f"{field} must be a text array")
    return value


def _command(value: Any) -> None:
    if not isinstance(value, dict):
        raise ValueError("command must be an object")
    returncode = value.get("returncode")
    if not isinstance(returncode, int) or isinstance(returncode, bool):
        raise ValueError("command.returncode must be an integer")
    for field in ("stdout_ref", "stderr_ref"):
        if not isinstance(value.get(field), str):
            raise ValueError(f"command.{field} must be a string")
