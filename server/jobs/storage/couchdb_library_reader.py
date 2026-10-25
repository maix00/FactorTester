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

    def factor_family_heads(self, source_kind: str, owner_ref: str = "") -> list[dict]:
        selector = {"kind": "factor_family_head", "source_kind": source_kind}
        if owner_ref:
            selector["owner_ref"] = owner_ref
        return self._find(selector)


class CouchDBLibraryWriter:
    def __init__(self, store) -> None:
        self.store = store

    def replace_product_groups(self, owner_ref: str, groups: list[dict]) -> int:
        import json

        existing = self._find({"kind": "product_group", "owner_ref": owner_ref})
        documents = []
        current = set()
        for index, group in enumerate(groups):
            if not isinstance(group, dict):
                continue
            group_id = str(group.get("id") or group.get("name") or "").strip()
            if not group_id:
                continue
            current.add(group_id)
            documents.append({
                "_id": f"product-group:{owner_ref}:{group_id}",
                "kind": "product_group", "owner_ref": owner_ref,
                "name": str(group.get("name") or ""), "sort_index": index,
                "payload": dict(group), "schema_version": 1,
            })
        for document in existing:
            group_id = str(document.get("_id") or "").rsplit(":", 1)[-1]
            if group_id not in current:
                documents.append({"_id": document["_id"], "_rev": document["_rev"],
                                  "_deleted": True})
        status, body = self.store._request(
            "POST", "_bulk_docs", json.dumps({"docs": documents}).encode(),
        )
        if status not in {201, 202}:
            raise RuntimeError(f"CouchDB product-group write failed: {status}")
        return len(documents)

    def _find(self, selector: dict) -> list[dict]:
        import json

        status, body = self.store._request(
            "POST", "_find", json.dumps({"selector": selector, "limit": 5000}).encode(),
        )
        if status != 200:
            raise RuntimeError(f"CouchDB _find failed: {status}")
        return list(json.loads(body).get("docs") or [])
