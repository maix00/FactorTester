from server.identity.device_migration_inventory import classify_devices

KEY = {"kty": "EC", "crv": "P-256", "x": "A" * 43, "y": "A" * 43}
IDENTITY = {"tr_identity_id": "stable", "keycloak_subject": "subject", "active": True}


def test_inventory_preserves_denials_and_never_exposes_public_keys():
    records = [
        {"device_id": "device-1234567890123456", "username": "alice", "public_key": KEY, "enabled": True},
        {"device_id": "device-1234567890123457", "username": "alice", "public_key": KEY, "enabled": False},
        {"device_id": "device-1234567890123458", "username": "missing", "public_key": KEY, "enabled": True},
    ]
    rows = classify_devices(manager_id="manager", records=records, identities={"alice": [IDENTITY]})
    assert [row["status"] for row in rows] == ["grant", "denied", "invalid_identity"]
    assert all("public_key" not in row for row in rows)


def test_inventory_refuses_duplicate_devices_and_ambiguous_users():
    record = {"device_id": "device-1234567890123456", "username": "alice", "public_key": KEY, "enabled": True}
    rows = classify_devices(manager_id="manager", records=[record, record], identities={"alice": [IDENTITY]})
    assert [row["status"] for row in rows] == ["conflict", "conflict"]
    rows = classify_devices(manager_id="manager", records=[record], identities={"alice": [IDENTITY, IDENTITY]})
    assert rows[0]["status"] == "invalid_identity"
