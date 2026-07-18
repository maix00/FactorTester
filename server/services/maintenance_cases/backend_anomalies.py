"""Backend-anomaly Adapter into the general Maintenance Case owner."""

from __future__ import annotations

import hashlib
from typing import Any

import orjson

from .store import MaintenanceCaseStore


_VERIFIER_DISPOSITIONS = {
    "confirmed_reliable",
    "backend_change_proposed",
    "research_input_issue",
}


def backend_anomaly_descriptor_hash(
    *,
    job_id: str,
    policy_hash: str,
    anomaly_codes: list[str],
) -> str:
    spec = _backend_anomaly_identity(
        job_id=job_id,
        policy_hash=policy_hash,
        anomaly_codes=anomaly_codes,
    )
    return hashlib.sha256(
        orjson.dumps(spec, option=orjson.OPT_SORT_KEYS)
    ).hexdigest()


def backend_anomaly_case_spec(
    *,
    owner_user_id: str,
    job_id: str,
    policy_hash: str,
    anomaly_codes: list[str],
    conversation_ref: str = "",
) -> dict[str, Any]:
    identity = _backend_anomaly_identity(
        job_id=job_id,
        policy_hash=policy_hash,
        anomaly_codes=anomaly_codes,
    )
    return {
        "owner_user_id": owner_user_id,
        "kind": "backend_anomaly",
        "descriptor_hash": hashlib.sha256(
            orjson.dumps(identity, option=orjson.OPT_SORT_KEYS)
        ).hexdigest(),
        "affected_refs": [f"job:{job_id}"],
        "change_refs": [
            f"assurance-policy:{policy_hash}",
            *(
                f"anomaly-code:{code}"
                for code in identity["anomaly_codes"]
            ),
        ],
        "conversation_ref": conversation_ref,
    }


def open_backend_anomaly(
    store: MaintenanceCaseStore,
    *,
    owner_user_id: str,
    job_id: str,
    policy_hash: str,
    anomaly_codes: list[str],
    conversation_ref: str = "",
) -> dict[str, Any]:
    return store.open_case(**backend_anomaly_case_spec(
        owner_user_id=owner_user_id,
        job_id=job_id,
        policy_hash=policy_hash,
        anomaly_codes=anomaly_codes,
        conversation_ref=conversation_ref,
    ))


def record_backend_verifier_result(
    store: MaintenanceCaseStore,
    *,
    owner_user_id: str,
    case_id: str,
    agent_id: str,
    disposition: str,
    evidence_refs: list[str],
    result_ref: str,
) -> dict[str, Any]:
    if disposition not in _VERIFIER_DISPOSITIONS:
        raise ValueError("invalid Backend Reviewer disposition")
    change_refs = [
        f"verifier-disposition:{disposition}",
        *evidence_refs,
    ]
    transition = {
        "confirmed_reliable": store.resolve_case,
        "backend_change_proposed": store.block_case,
        "research_input_issue": store.reject_case,
    }[disposition]
    return transition(
        case_id=case_id,
        owner_user_id=owner_user_id,
        agent_id=agent_id,
        result_ref=result_ref,
        change_refs=change_refs,
    )


def _backend_anomaly_identity(
    *,
    job_id: str,
    policy_hash: str,
    anomaly_codes: list[str],
) -> dict[str, Any]:
    if not isinstance(job_id, str) or not job_id.strip():
        raise ValueError("job_id is required")
    if (
        not isinstance(policy_hash, str)
        or len(policy_hash) != 64
        or any(
            character not in "0123456789abcdef"
            for character in policy_hash
        )
    ):
        raise ValueError("policy_hash must be sha256")
    if (
        not isinstance(anomaly_codes, list)
        or not anomaly_codes
        or not all(
            isinstance(code, str) and code.strip() and len(code) <= 128
            for code in anomaly_codes
        )
    ):
        raise ValueError("anomaly_codes must be a non-empty bounded array")
    return {
        "job_id": job_id,
        "policy_hash": policy_hash,
        "anomaly_codes": sorted(set(anomaly_codes)),
    }
