"""Resolve backend-registered settings for one group-test request."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from tools.backtest.settings import backtest_setting_registry, resolve_group_settings


def resolve_request_settings(
    snapshot: Mapping | None,
    group_ids: Sequence[str],
) -> dict[str, dict]:
    snapshot = snapshot if isinstance(snapshot, Mapping) else {}
    application_name = str(snapshot.get("application") or "group_test")
    if application_name != "group_test":
        raise ValueError(f"invalid backtest settings application: {application_name}")
    local_values = snapshot.get("local_values")
    group_values = snapshot.get("group_values")
    return resolve_group_settings(
        backtest_setting_registry.get(application_name),
        local_values=local_values if isinstance(local_values, Mapping) else {},
        group_values=group_values if isinstance(group_values, Mapping) else {},
        group_ids=group_ids,
    )
