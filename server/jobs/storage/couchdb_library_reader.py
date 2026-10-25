"""Opt-in CouchDB read-through for product-group and factor library rows."""

from __future__ import annotations

import json


class CouchDBLibraryReader:
    def __init__(self, store) -> None:
        self.store = store

    def _find(self, selector: dict) -> list[dict]:
        status, body = self.store._request(
            "POST", "_find",
            json.dumps({"selector": selector, "limit": 5000}).encode(),
        )
        if status != 200:
            raise RuntimeError(f"CouchDB _find failed: {status}")
        return list(json.loads(body).get("docs") or [])

    def product_groups(self, owner_ref: str) -> list[dict]:
        return [dict(doc.get("payload") or {}) for doc in self._find({
            "kind": "product_group", "owner_ref": owner_ref,
        }) if isinstance(doc.get("payload"), dict)]

    def factor_families(self, source_kind: str, owner_ref: str = "") -> list[dict]:
        selector = {"kind": "factor_family", "source_kind": source_kind}
        if owner_ref:
            selector["owner_ref"] = owner_ref
        return self._find(selector)
