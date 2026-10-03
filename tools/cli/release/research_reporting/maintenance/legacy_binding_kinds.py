"""Explicit type repair for bindings created before typed references."""

from __future__ import annotations

from ..authoring.inline_links import validate_typed_target


_REFERENCE_KINDS = {
    "evidence:": "evidence",
    "obligation:": "obligation",
    "task:": "task",
    "job:": "job",
    "claim:": "claim",
    "artifact:": "artifact",
    "report-requirement:": "report_requirement",
    "trace:": "checkpoint",
    "report-checkpoint:": "checkpoint",
    "run:": "run",
    "runspec:": "run_spec",
    "trial-plan:": "trial_plan",
    "delta:": "delta",
    "profile:": "profile",
}


def normalized_legacy_binding_kind(kind: str, target_ref: str) -> str:
    """Preserve valid types; otherwise use only explicit reference prefixes."""
    try:
        validate_typed_target(
            kind=kind, target_ref=target_ref, field="binding.target_ref",
        )
    except ValueError:
        for prefix, replacement in _REFERENCE_KINDS.items():
            if target_ref.startswith(prefix):
                return replacement
        raise ValueError(
            f"legacy report binding has no supported reference kind: {target_ref}"
        )
    return kind
