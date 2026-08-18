from __future__ import annotations

from server.manager.domain.accounts import manager_subordinate_users
from server.modules.single_factor_test.backtest_job_reads import _subordinate_users
from tools.data import account_manage


def _accounts() -> list[dict[str, object]]:
    return [
        {
            "username": "GTHT@testA@545963541963",
            "alias": "testA",
            "organization_id": "GTHT",
            "organization_name": "GTHT",
            "parent_username": "",
            "active": True,
        },
        {
            "username": "GTHT@MaxJJW@392452984564",
            "alias": "MaxJJW",
            "organization_id": "GTHT",
            "organization_name": "GTHT",
            "parent_username": "GTHT@testA@545963541963",
            "active": True,
        },
        {
            "username": "GTHT@grandchild@123456789012",
            "alias": "grandchild",
            "organization_id": "GTHT",
            "organization_name": "GTHT",
            "parent_username": "GTHT@MaxJJW@392452984564",
            "active": True,
        },
        {
            "username": "GTHT@inactive@123456789013",
            "alias": "inactive",
            "organization_id": "GTHT",
            "organization_name": "GTHT",
            "parent_username": "GTHT@testA@545963541963",
            "active": False,
        },
        {
            "username": "default@other-org@123456789014",
            "alias": "other-org",
            "organization_id": "default",
            "organization_name": "default",
            "parent_username": "GTHT@testA@545963541963",
            "active": True,
        },
    ]


def test_task_subordinates_are_direct_children_only(monkeypatch) -> None:
    monkeypatch.setattr(account_manage, "load_accounts", _accounts)
    test_a = "GTHT@testA@545963541963"
    max_jjw = "GTHT@MaxJJW@392452984564"

    assert [item["alias"] for item in account_manage.direct_subordinate_accounts_for(test_a)] == [
        "MaxJJW",
    ]
    assert [item["alias"] for item in account_manage.direct_subordinate_accounts_for(max_jjw)] == [
        "grandchild",
    ]
    assert manager_subordinate_users(test_a)[0]["username"] == max_jjw
    assert _subordinate_users(test_a)[0]["username"] == max_jjw

