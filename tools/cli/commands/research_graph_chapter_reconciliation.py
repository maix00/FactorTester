"""Durable recovery after a server transition but failed report sync."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tools.cli.release.research_reporting.authoring.tree_store import atomic_write
from tools.cli.release.research_reporting.package_layout import safe_package_component

from .research_graph_local_report import LocalGraphReport
from .research_graph_report_sync import synchronize_report_container


class ChapterReconciliationRequired(RuntimeError):
    """The server moved, but its local report container is pending."""


def load_pending(scope: LocalGraphReport) -> dict[str, Any] | None:
    path = _path(scope)
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Graph report reconciliation marker is invalid") from exc
    expected = {
        "schema_version", "profile_id", "instance_id", "branch_id",
        "report_container", "reason",
    }
    if (
        not isinstance(value, dict)
        or set(value) != expected
        or value.get("schema_version") != 2
        or value.get("profile_id") != scope.profile_id
        or value.get("instance_id") != scope.instance_id
        or value.get("branch_id") != scope.branch_id
        or not isinstance(value.get("report_container"), dict)
    ):
        raise ValueError("Graph report reconciliation marker fields are invalid")
    return value


def write_pending(
    scope: LocalGraphReport,
    *,
    container: dict[str, Any],
    reason: str,
) -> Path:
    path = _path(scope)
    payload = {
        "schema_version": 2,
        "profile_id": scope.profile_id,
        "instance_id": scope.instance_id,
        "branch_id": scope.branch_id,
        "report_container": container,
        "reason": reason,
    }
    atomic_write(path, json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode() + b"\n")
    return path


def reconcile_current_container(
    scope: LocalGraphReport,
    *,
    container: dict[str, Any],
) -> dict[str, Any]:
    pending = load_pending(scope)
    if pending is not None:
        synchronize_report_container(
            scope, container=pending["report_container"],
        )
        clear_pending(scope)
    return synchronize_report_container(scope, container=container)


def synchronize_transition_container(
    scope: LocalGraphReport,
    *,
    container: dict[str, Any],
) -> dict[str, Any]:
    try:
        result = synchronize_report_container(scope, container=container)
        clear_pending(scope)
        return result
    except Exception as exc:
        try:
            marker = write_pending(
                scope, container=container, reason=str(exc),
            )
            location = str(marker)
        except Exception as marker_error:
            location = "marker-write-failed: " + str(marker_error)
        raise ChapterReconciliationRequired(
            "server transition completed, but its report container "
            f"is pending reconciliation at {location}: {exc}"
        ) from exc


def clear_pending(scope: LocalGraphReport) -> None:
    path = _path(scope)
    if path.exists():
        path.unlink()


def _path(scope: LocalGraphReport) -> Path:
    profile = safe_package_component(scope.profile_id, field="profile_id")
    instance = safe_package_component(scope.instance_id, field="instance_id")
    branch = safe_package_component(scope.branch_id, field="branch_id")
    return (
        scope.client_root / "graph-report-reconciliation" / profile
        / f"{instance}--{branch}.json"
    )
