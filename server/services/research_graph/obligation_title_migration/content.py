"""Pure title migration for Research Cycle checkpoints and events."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from server.services.research_graph.protocol import json_hash
from server.services.research_graph.research_cycle import (
    validate_adjudication_proposal,
    validate_research_cycle_checkpoint,
    validate_search_exhaustion_proposal,
)
from server.services.research_graph.research_cycle.events import (
    apply_research_cycle_event,
)


def migrate_checkpoint(
    checkpoint: dict[str, Any],
    *,
    titles: dict[str, str],
) -> dict[str, Any]:
    """Add reviewed titles and recompute every title-dependent hash."""
    return migrate_checkpoint_with_hashes(
        checkpoint, titles=titles,
    )[0]


def migrate_checkpoint_with_hashes(
    checkpoint: dict[str, Any],
    *,
    titles: dict[str, str],
) -> tuple[dict[str, Any], dict[str, str]]:
    """Migrate one checkpoint and retain old-to-new pending proposal hashes."""
    value = deepcopy(checkpoint)
    value.pop("projection_hash", None)
    _title_obligations(value.get("obligations") or [], titles)
    value["pending_adjudications"] = [
        _migrate_adjudication(item, titles)
        for item in value.get("pending_adjudications") or []
    ]
    for field in ("pending_closure", "closure"):
        if value.get(field) is not None:
            value[field] = _migrate_closure(
                value[field],
                obligations=value["obligations"],
            )
    migrated = validate_research_cycle_checkpoint(value)
    return migrated, _checkpoint_proposal_hashes(checkpoint, migrated)


def migrate_events(
    checkpoint: dict[str, Any],
    events: list[dict[str, Any]],
    *,
    titles: dict[str, str],
    proposal_hashes: dict[str, str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Rewrite event hashes while replaying against the migrated checkpoint."""
    current = validate_research_cycle_checkpoint(checkpoint)
    migrated: list[dict[str, Any]] = []
    proposal_hashes = dict(proposal_hashes or {})
    catalog = _requirement_catalog(current, events)
    for index, original in enumerate(events):
        event = deepcopy(original)
        event_type = str(event.get("event_type") or "")
        if event_type == "adjudication_proposed":
            proposal = event.get("proposal") or {}
            old_hash = str(proposal.get("proposal_hash") or "")
            event["proposal"] = _migrate_adjudication(proposal, titles)
            proposal_hashes[old_hash] = event["proposal"]["proposal_hash"]
        elif event_type == "adjudication_decided":
            _replace_proposal_hash(event, proposal_hashes)
        elif event_type == "closure_proposed":
            proposal = event.get("proposal") or {}
            old_hash = str(proposal.get("proposal_hash") or "")
            event["proposal"] = _migrate_closure(
                proposal, obligations=current["obligations"],
            )
            proposal_hashes[old_hash] = event["proposal"]["proposal_hash"]
        elif event_type == "closure_decided":
            _replace_proposal_hash(event, proposal_hashes)
        try:
            current = apply_research_cycle_event(
                current,
                event,
                requirement_catalog=catalog,
            )
        except Exception as exc:
            pending = [
                str(item.get("proposal_hash") or "")
                for item in current.get("pending_adjudications") or []
            ]
            decision_hash = str(
                (event.get("decision") or {}).get("proposal_hash") or ""
            )
            raise ValueError(
                f"event {index} {event_type} failed; "
                f"decision_hash={decision_hash}; pending={pending}: {exc}"
                f"; hash_map={proposal_hashes}"
            ) from exc
        migrated.append(event)
    current.pop("projection_hash", None)
    return migrated, validate_research_cycle_checkpoint(current)


def _checkpoint_proposal_hashes(
    before: dict[str, Any],
    after: dict[str, Any],
) -> dict[str, str]:
    hashes: dict[str, str] = {}
    after_pending = {
        str(item.get("proposal_id") or ""): item
        for item in after.get("pending_adjudications") or []
    }
    for item in before.get("pending_adjudications") or []:
        migrated = after_pending.get(str(item.get("proposal_id") or ""))
        if migrated is not None:
            hashes[str(item.get("proposal_hash") or "")] = str(
                migrated.get("proposal_hash") or ""
            )
    for field in ("pending_closure", "closure"):
        old, new = before.get(field), after.get(field)
        if isinstance(old, dict) and isinstance(new, dict):
            hashes[str(old.get("proposal_hash") or "")] = str(
                new.get("proposal_hash") or ""
            )
    return {
        old: new for old, new in hashes.items()
        if old and new and old != new
    }


def _migrate_adjudication(
    proposal: dict[str, Any],
    titles: dict[str, str],
) -> dict[str, Any]:
    value = deepcopy(proposal)
    value.pop("proposal_hash", None)
    for delta in value.get("obligation_delta") or []:
        obligation = delta.get("obligation")
        if isinstance(obligation, dict):
            _title_obligations([obligation], titles)
    return validate_adjudication_proposal(value)


def _migrate_closure(
    proposal: dict[str, Any],
    *,
    obligations: list[dict[str, Any]],
) -> dict[str, Any]:
    value = deepcopy(proposal)
    value.pop("proposal_hash", None)
    value["obligation_projection_hash"] = json_hash(obligations)
    return validate_search_exhaustion_proposal(value)


def _title_obligations(
    obligations: list[dict[str, Any]],
    titles: dict[str, str],
) -> None:
    for obligation in obligations:
        obligation_id = str(obligation.get("obligation_id") or "")
        title = str(titles.get(obligation_id) or "").strip()
        if not title:
            raise ValueError(
                f"reviewed title is missing for obligation {obligation_id}"
            )
        obligation["title_zh"] = title


def _replace_proposal_hash(
    event: dict[str, Any],
    hashes: dict[str, str],
) -> None:
    decision = event.get("decision")
    if not isinstance(decision, dict):
        return
    old_hash = str(decision.get("proposal_hash") or "")
    if old_hash in hashes:
        decision["proposal_hash"] = hashes[old_hash]


def _requirement_catalog(
    checkpoint: dict[str, Any],
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    identifiers: set[str] = set()
    for obligation in checkpoint.get("obligations") or []:
        identifiers.update(obligation.get("requirement_refs") or [])
    for event in events:
        proposal = event.get("proposal") or {}
        for delta in proposal.get("obligation_delta") or []:
            identifiers.update(delta.get("from_requirement_refs") or [])
            identifiers.update(delta.get("to_requirement_refs") or [])
            obligation = delta.get("obligation") or {}
            identifiers.update(obligation.get("requirement_refs") or [])
    return {
        "requirements": [
            {"requirement_id": identifier}
            for identifier in sorted(identifiers)
        ],
    }
