from server.jobs.entitlements import entitlement_for_owner
from tools.data import account_manage


def test_developer_priority_requires_current_role(monkeypatch):
    monkeypatch.setattr(account_manage, "get_account", lambda owner: {
        "username": owner, "role": "developer",
    })
    monkeypatch.setattr(account_manage, "is_any_admin_account", lambda _account: False)
    monkeypatch.setattr(account_manage, "is_developer_account", lambda _account: False)
    assert entitlement_for_owner("alice").priority_class == "standard"
    monkeypatch.setattr(account_manage, "is_developer_account", lambda _account: True)
    assert entitlement_for_owner("alice").priority_class == "high"
