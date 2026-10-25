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
        }


def put_object(store, obj: VersionedObject) -> None:
    store._request("PUT", obj.ref, json.dumps(obj.to_doc()).encode())


def get_object(store, ref: str) -> dict[str, Any]:
    return json.loads(store._request("GET", ref)[1])
