"""Server-owned scheduling entitlement snapshots."""

from __future__ import annotations

from .models import SchedulingEntitlement


def entitlement_for_owner(owner: str) -> SchedulingEntitlement:
    from tools.data.account_manage import (
        ROLE_DEVELOPER,
        get_account,
        is_any_admin_account,
    )

    account = get_account(owner) or {}
    configured = account.get("research_job_entitlement")
    if isinstance(configured, dict):
        priority_class = str(configured.get("priority_class") or "standard")
        if priority_class not in {"low", "standard", "high", "admin"}:
            priority_class = "standard"
        return SchedulingEntitlement(
            priority_class=priority_class,
            weight=max(0.1, min(100.0, float(configured.get("weight") or 1.0))),
            max_queue_delay_seconds=max(
                0.0, float(configured.get("max_queue_delay_seconds") or 300.0)
            ),
            bypass_data_affinity=bool(configured.get("bypass_data_affinity")),
            reserved_capacity_class=str(configured.get("reserved_capacity_class") or ""),
            max_concurrency=max(1, min(8, int(configured.get("max_concurrency") or 1))),
        )
    if is_any_admin_account(account):
        return SchedulingEntitlement(
            priority_class="admin",
            weight=4.0,
            bypass_data_affinity=True,
            reserved_capacity_class="research-admin",
            max_concurrency=2,
        )
    if str(account.get("role") or "") == ROLE_DEVELOPER:
        return SchedulingEntitlement(
            priority_class="high", weight=2.0, max_concurrency=2,
        )
    return SchedulingEntitlement()
