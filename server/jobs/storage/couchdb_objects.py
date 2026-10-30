"""Versioned Factor/Strategy documents in CouchDB (reports use report module)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class VersionedObject:
    ref: str
    kind: str          # factor_version | strategy_version
    owner: str
    payload: dict[str, Any]
    schema_version: int = 1
    links: dict[str, str] = field(default_factory=dict)
    keycloak_resource_id: str = ""
    owner_subject: str = field(default="", repr=False, compare=False)

    def to_doc(self) -> dict[str, Any]:
        if self.kind not in {"factor_version", "strategy_version"}:
            raise ValueError("unsupported object kind")
        return {
            "_id": self.ref,
            "schema_version": self.schema_version,
            "kind": self.kind,
            "owner": self.owner,
            "payload": dict(self.payload),
            "links": dict(self.links),
            **({"keycloak_resource_id": self.keycloak_resource_id}
               if self.keycloak_resource_id else {}),
        }


def put_object(store, obj: VersionedObject) -> None:
    document = obj.to_doc()
    from server.identity.auth_mode import keycloak_enabled
    if keycloak_enabled() and not document.get("keycloak_resource_id"):
        from server.identity.keycloak_authorization import ensure_keycloak_resource

        if not obj.owner_subject:
            raise PermissionError("Keycloak resource registration requires a verified owner")
        document["keycloak_resource_id"] = ensure_keycloak_resource(
            resource_type=obj.kind, resource_ref=obj.ref,
            owner_subject=obj.owner_subject,
        )
    store._request("PUT", obj.ref, json.dumps(document).encode())


def get_object(store, ref: str) -> dict[str, Any]:
    return json.loads(store._request("GET", ref)[1])
