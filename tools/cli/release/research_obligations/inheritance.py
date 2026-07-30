"""Fork and continuation inheritance for one branch obligation ledger."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from .ledger import (
    append_event,
    canonicalize_ledger,
    initialize_ledger,
    ledger_path,
    load_ledger,
    write_ledger,
)
from .packet import (
    branch_identity,
    obligations as packet_obligations,
    requirements as packet_requirements,
)
from .projection import (
    project_requirement_coverage,
    requirement_title_overrides,
)


def inherit_obligation_ledger(
    *,
    source_package_root: Path,
    target_package_root: Path,
    source_branch_id: str,
    target_branch_id: str,
    target_instance_id: str,
    target_packet: dict[str, Any],
    inheritance_kind: str,
) -> dict[str, Any]:
    """Copy one current projection and bind it to the exact target identity."""
    target_path = ledger_path(target_package_root, target_branch_id)
    expected_branch = branch_identity(
        instance_id=target_instance_id,
        branch_id=target_branch_id,
        packet=target_packet,
    )
    if target_path.exists():
        current = load_ledger(target_package_root, target_branch_id)
        if current["branch"] != expected_branch:
            raise ValueError(
                "existing inherited obligation ledger identity conflicts"
            )
        return {"ledger": current, "inherited": False}

    source_path = ledger_path(source_package_root, source_branch_id)
    source = (
        load_ledger(source_package_root, source_branch_id)
        if source_path.exists() else None
    )
    server_obligations = packet_obligations(target_packet)
    obligations = deepcopy(
        source["current_projection"]["obligations"]
        if source is not None else server_obligations
    )
    if _obligation_projection(obligations) != _obligation_projection(
        server_obligations
    ):
        raise ValueError(
            "source obligation ledger does not match target server checkpoint"
        )
    ledger = initialize_ledger(
        branch_ref=expected_branch["branch_ref"],
        graph_ref=expected_branch["graph_ref"],
        current_node=expected_branch["current_node"],
        context_ref=expected_branch["context_ref"],
        checkpoint_ref=expected_branch["checkpoint_ref"],
        obligations=obligations,
    )
    ledger["current_projection"]["requirement_coverage"] = (
        project_requirement_coverage(
            requirements=packet_requirements(target_packet),
            obligations=obligations,
            title_overrides=(
                requirement_title_overrides(source)
                if source is not None else None
            ),
        )
    )
    ledger = canonicalize_ledger(ledger)
    ledger = append_event(
        ledger,
        event_type="forked",
        payload={
            "inheritance_kind": inheritance_kind,
            "source_branch_ref": (
                source["branch"]["branch_ref"] if source is not None
                else f"local-branch:{source_branch_id}"
            ),
            "source_projection_hash": (
                source["current_projection"]["projection_hash"]
                if source is not None else ""
            ),
            "source_generation": (
                int(source["generation"]) if source is not None else None
            ),
            "source_ledger_present": source is not None,
            "coverage_snapshot": ledger["current_projection"][
                "requirement_coverage"
            ],
        },
    )
    return {
        "ledger": write_ledger(
            target_package_root, target_branch_id, ledger,
        ),
        "inherited": True,
    }


def _obligation_projection(
    obligations: list[dict[str, Any]],
) -> list[tuple[str, str, tuple[str, ...]]]:
    return sorted(
        (
            str(item.get("obligation_id") or ""),
            str(item.get("status") or ""),
            tuple(dict.fromkeys(
                str(ref).removeprefix("requirement:")
                for ref in item.get("requirement_refs") or []
            )),
        )
        for item in obligations
    )
