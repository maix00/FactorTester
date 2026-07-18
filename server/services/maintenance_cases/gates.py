"""Reference-only approval Gates backed by one Maintenance Case row."""

from __future__ import annotations

import hashlib
from typing import Any

import orjson

from .store import MaintenanceCaseStore


_GATE_KIND = "approval_gate"
_REVIEW_DISPOSITIONS = {"approved", "disagreed", "rejected"}
_GRILL_DISPOSITIONS = {"approved", "rejected", "quarantined", "frozen"}
_MAX_REF_LENGTH = 512


def open_gate(
    store: MaintenanceCaseStore,
    *,
    owner_user_id: str,
    coordinator_agent_id: str,
    proposal_ref: str,
    proposer_identity_ref: str,
    action: str,
    target_hash: str,
    conversation_ref: str,
    proposal_evidence_refs: list[str] | None = None,
) -> dict[str, Any]:
    """Open and claim one exact-action Gate using external references only."""
    _require_ref("proposal_ref", proposal_ref)
    _require_ref("proposer_identity_ref", proposer_identity_ref)
    _require_action(action)
    _require_hash(target_hash)
    _require_authenticated_conversation(conversation_ref)
    proposal_evidence = _require_refs(
        "proposal_evidence_refs",
        proposal_evidence_refs or [],
    )
    identity = {
        "proposal_ref": proposal_ref,
        "action": action,
        "target_hash": target_hash,
    }
    case = store.open_case(
        owner_user_id=owner_user_id,
        kind=_GATE_KIND,
        descriptor_hash=hashlib.sha256(orjson.dumps(
            identity,
            option=orjson.OPT_SORT_KEYS,
        )).hexdigest(),
        affected_refs=[
            proposal_ref,
            f"gate-proposer:{proposer_identity_ref}",
            f"gate-action:{action}",
            f"gate-target-hash:{target_hash}",
            *proposal_evidence,
        ],
        change_refs=[],
        conversation_ref=conversation_ref,
    )
    return store.claim_case(
        owner_user_id=owner_user_id,
        case_id=case["case_id"],
        agent_id=coordinator_agent_id,
    )


def record_gate_review(
    store: MaintenanceCaseStore,
    *,
    owner_user_id: str,
    case_id: str,
    coordinator_agent_id: str,
    reviewer_identity_ref: str,
    disposition: str,
    evidence_refs: list[str],
) -> dict[str, Any]:
    """Append one independent reviewer decision as bounded references."""
    _require_ref("reviewer_identity_ref", reviewer_identity_ref)
    if disposition not in _REVIEW_DISPOSITIONS:
        raise ValueError("invalid Gate review disposition")
    evidence = _require_refs("evidence_refs", evidence_refs)
    case = _require_gate_case(
        store,
        owner_user_id=owner_user_id,
        case_id=case_id,
    )
    if _has_prefix(case, "gate-approval:"):
        raise ValueError("Gate is already approved")
    if _has_prefix(case, "gate-validation:"):
        raise ValueError("Gate review is frozen after validation")
    proposer = _single_suffix(case["affected_refs"], "gate-proposer:")
    if reviewer_identity_ref == proposer:
        raise ValueError("Gate reviewer must be independent from proposer")
    reviews = _review_entries(case)
    reviewer_hash = hashlib.sha256(
        reviewer_identity_ref.encode()
    ).hexdigest()
    existing = reviews.get(reviewer_hash)
    if existing is not None:
        if existing != disposition:
            raise ValueError("Gate reviewer disposition cannot change")
        return store.record_progress(
            owner_user_id=owner_user_id,
            case_id=case_id,
            agent_id=coordinator_agent_id,
            result_ref=f"reviewer:{reviewer_hash}",
            change_refs=evidence,
        )
    if _review_state(reviews)["ready"]:
        raise ValueError("Gate independent review is already sufficient")
    if len(reviews) >= 3:
        raise ValueError("Gate accepts at most three independent reviewers")
    return store.record_progress(
        owner_user_id=owner_user_id,
        case_id=case_id,
        agent_id=coordinator_agent_id,
        result_ref=f"reviewer:{reviewer_hash}",
        change_refs=[
            f"gate-reviewer:{reviewer_identity_ref}",
            f"gate-review:{reviewer_hash}:{disposition}",
            *evidence,
        ],
    )


def approve_gate(
    store: MaintenanceCaseStore,
    *,
    owner_user_id: str,
    case_id: str,
    coordinator_agent_id: str,
    action: str,
    target_hash: str,
    approval_ref: str,
) -> dict[str, Any]:
    """Record exact action/hash approval after the independent audit."""
    _require_action(action)
    _require_hash(target_hash)
    _require_ref("approval_ref", approval_ref)
    case = _require_gate_case(
        store,
        owner_user_id=owner_user_id,
        case_id=case_id,
    )
    _require_exact_target(case, action=action, target_hash=target_hash)
    if not _review_state(_review_entries(case))["ready"]:
        raise ValueError("Gate requires an independent approval majority")
    if not any(
        ref.startswith("gate-validation:") and ref.endswith(":passed")
        for ref in case["change_refs"]
    ):
        raise ValueError("Gate requires deterministic validation to pass")
    if not any(
        ref.startswith("gate-grill:") and ref.endswith(":approved")
        for ref in case["change_refs"]
    ):
        raise ValueError("Gate requires an approved grill audit")
    existing = [
        ref for ref in case["change_refs"]
        if ref.startswith("gate-approval:")
    ]
    marker = f"gate-approval:{approval_ref}"
    if existing and existing != [marker]:
        raise ValueError("Gate exact approval cannot change")
    return store.block_case(
        owner_user_id=owner_user_id,
        case_id=case_id,
        agent_id=coordinator_agent_id,
        result_ref=approval_ref,
        change_refs=[marker],
    )


def record_gate_grill(
    store: MaintenanceCaseStore,
    *,
    owner_user_id: str,
    case_id: str,
    coordinator_agent_id: str,
    disposition: str,
    grill_ref: str,
) -> dict[str, Any]:
    """Record an independent grill result; non-approval fails closed."""
    if disposition not in _GRILL_DISPOSITIONS:
        raise ValueError("invalid Gate grill disposition")
    _require_ref("grill_ref", grill_ref)
    case = _require_gate_case(
        store,
        owner_user_id=owner_user_id,
        case_id=case_id,
    )
    if not any(
        ref.startswith("gate-validation:") and ref.endswith(":passed")
        for ref in case["change_refs"]
    ):
        raise ValueError("Gate requires deterministic validation to pass")
    if _has_prefix(case, "gate-approval:"):
        raise ValueError("Gate is already approved")
    marker = f"gate-grill:{grill_ref}:{disposition}"
    existing = [
        ref for ref in case["change_refs"]
        if ref.startswith("gate-grill:")
    ]
    if existing and existing != [marker]:
        raise ValueError("Gate grill disposition cannot change")
    transition = (
        store.block_case
        if disposition == "approved"
        else store.reject_case
    )
    return transition(
        owner_user_id=owner_user_id,
        case_id=case_id,
        agent_id=coordinator_agent_id,
        result_ref=grill_ref,
        change_refs=[marker],
    )


def record_gate_validation(
    store: MaintenanceCaseStore,
    *,
    owner_user_id: str,
    case_id: str,
    coordinator_agent_id: str,
    validation_summary_hash: str,
) -> dict[str, Any]:
    """Record passed deterministic and token gates by server summary hash."""
    _require_hash(validation_summary_hash)
    case = _require_gate_case(
        store,
        owner_user_id=owner_user_id,
        case_id=case_id,
    )
    if not _review_state(_review_entries(case))["ready"]:
        raise ValueError("Gate requires an independent approval majority")
    if _has_prefix(case, "gate-approval:"):
        raise ValueError("Gate is already approved")
    marker = f"gate-validation:{validation_summary_hash}:passed"
    existing = [
        ref for ref in case["change_refs"]
        if ref.startswith("gate-validation:")
    ]
    if existing and existing != [marker]:
        raise ValueError("Gate validation summary cannot change")
    return store.record_progress(
        owner_user_id=owner_user_id,
        case_id=case_id,
        agent_id=coordinator_agent_id,
        result_ref=f"validation-summary:{validation_summary_hash}",
        change_refs=[marker],
    )


def consume_gate_effect(
    store: MaintenanceCaseStore,
    *,
    owner_user_id: str,
    case_id: str,
    coordinator_agent_id: str,
    action: str,
    target_hash: str,
    effect_ref: str,
) -> dict[str, Any]:
    """Atomically consume one approved exact-action Gate."""
    _require_action(action)
    _require_hash(target_hash)
    _require_ref("effect_ref", effect_ref)
    case = _require_gate_case(
        store,
        owner_user_id=owner_user_id,
        case_id=case_id,
    )
    _require_exact_target(case, action=action, target_hash=target_hash)
    if (
        not _has_prefix(case, "gate-approval:")
        or not any(
            ref.startswith("gate-grill:") and ref.endswith(":approved")
            for ref in case["change_refs"]
        )
    ):
        raise ValueError("Gate requires grill and exact approval references")
    return store.consume_case_effect(
        owner_user_id=owner_user_id,
        case_id=case_id,
        agent_id=coordinator_agent_id,
        effect_ref=effect_ref,
        change_refs=[f"gate-effect:{effect_ref}"],
    )


def _require_gate_case(
    store: MaintenanceCaseStore,
    *,
    owner_user_id: str,
    case_id: str,
) -> dict[str, Any]:
    case = store.load_case(
        owner_user_id=owner_user_id,
        case_id=case_id,
    )
    if case["kind"] != _GATE_KIND:
        raise ValueError("Maintenance Case is not an approval Gate")
    return case


def _review_entries(case: dict[str, Any]) -> dict[str, str]:
    reviews: dict[str, str] = {}
    for ref in case["change_refs"]:
        if not ref.startswith("gate-review:"):
            continue
        _, reviewer_hash, disposition = ref.split(":", 2)
        reviews[reviewer_hash] = disposition
    return reviews


def _review_state(reviews: dict[str, str]) -> dict[str, Any]:
    dispositions = list(reviews.values())
    disagreement = any(value != "approved" for value in dispositions)
    required = 3 if disagreement else 1
    approvals = dispositions.count("approved")
    return {
        "ready": (
            len(dispositions) >= required
            and approvals > len(dispositions) // 2
        ),
        "required_reviewers": required,
    }


def _require_exact_target(
    case: dict[str, Any],
    *,
    action: str,
    target_hash: str,
) -> None:
    if (
        f"gate-action:{action}" not in case["affected_refs"]
        or f"gate-target-hash:{target_hash}" not in case["affected_refs"]
    ):
        raise ValueError("Gate action or target hash does not match")


def _has_prefix(case: dict[str, Any], prefix: str) -> bool:
    return any(ref.startswith(prefix) for ref in case["change_refs"])


def _single_suffix(refs: list[str], prefix: str) -> str:
    matches = [ref[len(prefix):] for ref in refs if ref.startswith(prefix)]
    if len(matches) != 1:
        raise ValueError("Gate identity references are invalid")
    return matches[0]


def _require_action(value: str) -> None:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 128
    ):
        raise ValueError("action must be a bounded exact value")


def _require_hash(value: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError("target_hash must be sha256")


def _require_ref(field: str, value: str) -> None:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > _MAX_REF_LENGTH - 32
    ):
        raise ValueError(f"{field} must be a bounded external reference")
    if value.startswith("gate-"):
        raise ValueError(f"{field} uses the reserved gate marker namespace")


def _require_refs(field: str, values: list[str]) -> list[str]:
    if not isinstance(values, list):
        raise ValueError(f"{field} must be an array of references")
    for value in values:
        _require_ref(field, value)
    return list(dict.fromkeys(values))


def _require_authenticated_conversation(value: str) -> None:
    _require_ref("conversation_ref", value)
    if not value.startswith("auth-conversation:"):
        raise ValueError("Gate requires an authenticated conversation ref")
