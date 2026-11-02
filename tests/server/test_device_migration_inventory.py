from server.identity.device_migration_inventory import classify_devices

KEY = {"kty": "EC", "crv": "P-256", "x": "A" * 43, "y": "A" * 43}
IDENTITY = {"tr_identity_id": "stable", "keycloak_subject": "subject", "active": True}


def test_inventory_preserves_denials_and_never_exposes_public_keys():
    records = [
        {"device_id": "device-1234567890123456", "username": "alice", "source_server_id": "manager", "public_key": KEY, "enabled": True},
        {"device_id": "device-1234567890123457", "username": "alice", "source_server_id": "manager", "public_key": KEY, "enabled": False},
        {"device_id": "device-1234567890123458", "username": "missing", "source_server_id": "manager", "public_key": KEY, "enabled": True},
    ]
    rows = classify_devices(manager_id="manager", records=records, identities={"alice": [IDENTITY]})
    assert [row["status"] for row in rows] == ["grant", "denied", "invalid_identity"]
    assert all("public_key" not in row for row in rows)


def test_inventory_refuses_duplicate_devices_and_ambiguous_users():
    record = {"device_id": "device-1234567890123456", "username": "alice", "source_server_id": "manager", "public_key": KEY, "enabled": True}
    rows = classify_devices(manager_id="manager", records=[record, record], identities={"alice": [IDENTITY]})
    assert [row["status"] for row in rows] == ["conflict", "conflict"]
    rows = classify_devices(manager_id="manager", records=[record], identities={"alice": [IDENTITY, IDENTITY]})
    assert rows[0]["status"] == "invalid_identity"


def test_inventory_rejects_normalized_collisions_and_malformed_stored_keys():
    record = {"device_id": "device-1234567890123456", "username": "alice",
              "source_server_id": "manager", "public_key": KEY, "enabled": True}
    padded = {**record, "device_id": "  " + record["device_id"] + "  "}
    rows = classify_devices(manager_id="manager", records=[record, padded], identities={"alice": [IDENTITY]})
    assert [row["status"] for row in rows] == ["conflict", "conflict"]
    assert [row["device_id"] for row in rows] == [record["device_id"], padded["device_id"]]
    assert all("resource_ref" not in row for row in rows)
    for malformed in (padded, {**record, "source_server_id": " manager "},
                      {**record, "device_id": 1234567890123456}):
        row, = classify_devices(manager_id="manager", records=[malformed], identities={"alice": [IDENTITY]})
        assert row["status"] == "needs_repair" and "resource_ref" not in row


def test_same_device_registered_by_two_managers_is_not_a_local_conflict():
    record = {"device_id": "device-1234567890123456", "username": "alice",
              "source_server_id": "manager", "public_key": KEY, "enabled": True}
    rows = classify_devices(manager_id="manager", records=[record, {**record, "source_server_id": "other"}],
                            identities={"alice": [IDENTITY]})
    assert [row["status"] for row in rows] == ["grant", "outside_manager"]


def test_inventory_refuses_missing_or_different_server_and_invalid_enabled():
    base = {"device_id": "device-1234567890123456", "username": "alice", "public_key": KEY, "enabled": True}
    for change, expected in [({}, "needs_repair"), ({"source_server_id": "elsewhere"}, "outside_manager"),
                             ({"source_server_id": "manager", "enabled": "false"}, "needs_repair")]:
        row = classify_devices(manager_id="manager", records=[base | change], identities={"alice": [IDENTITY]})[0]
        assert row["status"] == expected
        assert "resource_ref" not in row


def test_inventory_requires_manager_identity():
    import pytest
    with pytest.raises(ValueError):
        classify_devices(manager_id="", records=[], identities={})


def test_legacy_public_denial_is_never_silently_converted_to_grant():
    base = {"device_id": "device-1234567890123456", "username": "alice", "source_server_id": "manager", "public_key": KEY, "enabled": True}
    rows = classify_devices(manager_id="manager", records=[base | {"public_access": False}], identities={"alice": [IDENTITY]})
    assert rows[0]["status"] == "legacy_policy_review"
    rows = classify_devices(manager_id="manager", records=[base | {"enabled": False, "public_access": False}], identities={"alice": [IDENTITY]})
    assert rows[0]["status"] == "denied"
    rows = classify_devices(manager_id="manager", records=[base | {"public_access": "false"}], identities={"alice": [IDENTITY]})
    assert rows[0]["status"] == "needs_repair"
