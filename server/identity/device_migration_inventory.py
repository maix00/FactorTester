"""Read-only classification of legacy device grants before Keycloak cutover."""
from __future__ import annotations

from collections import Counter

from server.identity.keycloak_device import device_resource_ref


def classify_devices(*, manager_id: str, records: list[dict], identities: dict[str, list[dict]]) -> list[dict]:
    """Map each record without creating grants or exposing public keys.

    The caller supplies a scoped, freshly verified Keycloak directory. Ambiguous
    identities and duplicate device IDs require repair rather than a grant.
    """
    target = str(manager_id or "").strip()
    if not target or len(target) > 256:
        raise ValueError("Manager identity is required")
    # Keycloak's device reference normalises surrounding whitespace. Detect
    # collisions using that same identity before considering any grant.
    counts = Counter((str(row.get("source_server_id") or "").strip(),
                      str(row.get("device_id") or "").strip()) for row in records)
    result = []
    for row in records:
        device_id = str(row.get("device_id") or "")
        owner = str(row.get("username") or "")
        item = {"device_id": device_id, "username": owner}
        source = str(row.get("source_server_id") or "").strip()
        matches = identities.get(owner, [])
        if (not source or type(row.get("source_server_id")) is not str
                or row["source_server_id"] != source or type(row.get("enabled")) is not bool):
            item["status"] = "needs_repair"
        elif source != target:
            # Mirror records cannot be re-granted under this Manager's identity.
            item["status"] = "outside_manager"
        elif counts[(source, device_id.strip())] != 1:
            item["status"] = "conflict"
        elif type(row.get("device_id")) is not str or device_id != device_id.strip():
            # The Manager's metadata lookup uses the stored key, so changing
            # it silently in Keycloak would not migrate the actual device.
            item["status"] = "needs_repair"
        elif len(matches) != 1:
            item["status"] = "invalid_identity"
        else:
            identity = matches[0]
            stable = str(identity.get("tr_identity_id") or "")
            subject = str(identity.get("keycloak_subject") or "")
            if not stable or not subject or identity.get("active") is not True:
                item["status"] = "invalid_identity"
            else:
                try:
                    item["resource_ref"] = device_resource_ref(server_id=target, identity_id=stable,
                                                               device_id=device_id, public_key=row.get("public_key"))
                    old_public = row.get("public_access")
                    if "public_access" in row and type(old_public) is not bool:
                        item["status"] = "needs_repair"
                        item.pop("resource_ref", None)
                    elif row.get("enabled") is False:
                        item["status"] = "denied"
                    elif old_public is False:
                        # Some installations already converted this legacy
                        # field to the allowlist policy and others did not.
                        # Do not silently create a grant from an ambiguous bit.
                        item["status"] = "legacy_policy_review"
                    else:
                        item["status"] = "grant"
                except (TypeError, ValueError):
                    item["status"] = "needs_repair"
        result.append(item)
    return result
