"""Report-tree queries used by current-node report publication."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import time
from typing import Any

from ...local_profile import LocalProfileStore
from ..authoring.tree_model import load_snapshot


def branch_history(
    *, client_root: Path, profile_id: str, agent_id: str, carrier: dict[str, Any],
) -> tuple[set[tuple[str, str, str]], dict[str, Any], dict[str, Any] | None]:
    profile, record = _record(client_root, profile_id, agent_id, carrier)
    package = Path(profile["workspace_root"]) / "research" / carrier["work_package_ref"].removeprefix("work-package:")
    branch_id = str(carrier["branch_ref"]).split(":")[-1]
    snapshot = load_snapshot(package_root=package, branch_id=branch_id)
    identities = {
        _identity(binding.get("data") or {}) for binding in snapshot["bindings"]
        if binding.get("kind") == "report_requirement"
        and _identity(binding.get("data") or {}) is not None
    }
    expected = f"artifact:research/{carrier['work_package_ref'].removeprefix('work-package:')}/branches/{branch_id}/authoring/HEAD.json"
    artifacts = [deepcopy(item) for item in record["artifacts"] if item.get("artifact_ref") == expected]
    return identities, record, artifacts[0] if len(artifacts) == 1 else None


def publication_clock(
    *, client_root: Path, profile_id: str, agent_id: str, carrier: dict[str, Any],
    checkpoint_ref: str, minimum: float,
) -> tuple[str, float]:
    _, record = _record(client_root, profile_id, agent_id, carrier)
    previous = str(record.get("checkpoint_ref") or "")
    previous_time = float(record.get("updated_at") or 0)
    if previous == checkpoint_ref:
        return previous, previous_time
    return previous, max(time.time(), minimum, previous_time + 0.000001)


def item_identity(item: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(item.get("report_requirement_id") or ""),
        str(item.get("subject_ref") or ""),
        str(item.get("item_hash") or "").removeprefix("report-item:sha256:"),
    )


def _record(client_root: Path, profile_id: str, agent_id: str, carrier: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    profile = LocalProfileStore(client_root).load(profile_id)
    matches = [
        item for item in profile["research_records"]
        if item["graph_instance_ref"] == carrier.get("work_package_ref")
        and item["graph_branch_ref"] == carrier.get("branch_ref")
        and item["agent_id"] == agent_id
    ]
    if len(matches) != 1:
        raise ValueError("checkpoint requires exactly one matching local research record")
    return profile, matches[0]


def _identity(data: dict[str, Any]) -> tuple[str, str, str] | None:
    ref = str(data.get("report_item_ref") or "").removeprefix("report-item:sha256:")
    requirement, subject = str(data.get("report_requirement_id") or ""), str(data.get("subject_ref") or "")
    return (requirement, subject, ref) if requirement and subject and ref else None
