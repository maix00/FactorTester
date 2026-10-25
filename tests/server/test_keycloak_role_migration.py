from scripts.migrations.keycloak_roles import entries_for_accounts


def test_super_admin_and_operator_get_managed_permissions():
    entries = entries_for_accounts([
        {"username": "root", "role": "super_admin", "is_admin": True},
        {"username": "ops", "role": "operator"},
        {"username": "alice", "role": "user"},
    ])
    subjects = {entry["subject"] for entry in entries}
    assert subjects == {"user:root", "user:ops"}
    assert all(entry["resource_type"] == "admin_console" for entry in entries)
