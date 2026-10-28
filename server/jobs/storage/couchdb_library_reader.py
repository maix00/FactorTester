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


    def strategies(self, owner_ref: str = "") -> list[dict]:
        selector = {"kind": "strategy_version"}
        if owner_ref:
            selector["owner_ref"] = owner_ref
        return self._find(selector)

    def strategy(self, strategy_ref: str) -> dict | None:
        import json

        try:
            _, body = self.store._request("GET", strategy_ref)
        except Exception:
            return None
        document = json.loads(body)
        return document if document.get("kind") == "strategy_version" else None

    def strategy_shares(self, strategy_ref: str) -> list[str]:
        documents = self._find({"kind": "strategy_share", "strategy_ref": strategy_ref})
        return sorted(str(doc.get("principal_ref") or "") for doc in documents)

    def shared_strategies(self, principal_ref: str) -> list[str]:
        documents = self._find({"kind": "strategy_share", "principal_ref": principal_ref})
        return [str(doc.get("strategy_ref") or "") for doc in documents]

    def revisions(self, strategy_ref: str) -> list[dict]:
        documents = self._find({"kind": "strategy_revision", "strategy_ref": strategy_ref})
        return [dict(doc.get("payload") or {}) for doc in documents]

    def revision(self, revision_ref: str) -> dict | None:
        import json

        try:
            _, body = self.store._request("GET", revision_ref)
        except Exception:
            return None
        document = json.loads(body)
        return document if document.get("kind") == "strategy_revision" else None

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

    def upsert_factor_family(self, source_kind: str, owner_ref: str, row: dict) -> None:
        import json

        factor_id = str(row.get("factor_id") or "").strip()
        if not factor_id:
            return
        doc_id = f"factor-family:{owner_ref or 'public'}:{factor_id}"
        try:
            status, body = self.store._request("GET", doc_id)
            document = json.loads(body)
            document["_rev"] = document["_rev"]
        except Exception:
            document = {
                "_id": doc_id, "schema_version": 1, "kind": "factor_family",
                "source_kind": source_kind, "factor_id": factor_id,
                "owner_ref": owner_ref,
            }
        document["catalog"] = dict(row.get("catalog") or row)
        document["source_kind"] = source_kind
        document["owner_ref"] = owner_ref
        self.store._request("PUT", doc_id, json.dumps(document).encode())



    def upsert_strategy(self, strategy_ref: str, entry: dict, revision: dict | None) -> None:
        import json

        doc_id = strategy_ref
        document = {
            "_id": doc_id, "schema_version": 1, "kind": "strategy_version",
            "strategy_ref": strategy_ref, "owner_ref": entry.get("owner_ref") or "",
            "payload": {"entry": entry, "revision": revision},
        }
        try:
            _, body = self.store._request("GET", doc_id)
            document["_rev"] = json.loads(body)["_rev"]
        except Exception:
            pass
        self.store._request("PUT", doc_id, json.dumps(document).encode())
        if isinstance(revision, dict) and revision.get("revision_ref"):
            revision_ref = str(revision["revision_ref"])
            revision_doc = {
                "_id": revision_ref, "schema_version": 1,
                "kind": "strategy_revision", "strategy_ref": strategy_ref,
                "payload": dict(revision),
            }
            try:
                _, body = self.store._request("GET", revision_ref)
                revision_doc["_rev"] = json.loads(body)["_rev"]
            except Exception:
                pass
            self.store._request("PUT", revision_ref, json.dumps(revision_doc).encode())

    def grant_strategy_share(self, strategy_ref: str, principal_ref: str) -> None:
        import json

        doc_id = f"strategy-share:{strategy_ref}:{principal_ref}"
        document = {"_id": doc_id, "schema_version": 1, "kind": "strategy_share",
                    "strategy_ref": strategy_ref, "principal_ref": principal_ref}
        self.store._request("PUT", doc_id, json.dumps(document).encode())

    def revoke_strategy_share(self, strategy_ref: str, principal_ref: str) -> None:
        import json

        doc_id = f"strategy-share:{strategy_ref}:{principal_ref}"
        try:
            _, body = self.store._request("GET", doc_id)
        except Exception:
            return
        document = json.loads(body)
        document.update({"_deleted": True, "_rev": document["_rev"]})
        self.store._request("PUT", doc_id, json.dumps(document).encode())

    def delete_strategy(self, strategy_ref: str) -> None:
        import json

        try:
            _, body = self.store._request("GET", strategy_ref)
        except Exception:
            return
        document = json.loads(body)
        document.update({"_deleted": True, "_rev": document["_rev"]})
        self.store._request("PUT", strategy_ref, json.dumps(document).encode())

    def strategies(self, owner_ref: str = "") -> list[dict]:
        selector = {"kind": "strategy_version"}
        if owner_ref:
            selector["owner_ref"] = owner_ref
        return self._find(selector)

    def strategy(self, strategy_ref: str) -> dict | None:
        import json

        try:
            _, body = self.store._request("GET", strategy_ref)
        except Exception:
            return None
        document = json.loads(body)
        if document.get("kind") != "strategy_version":
            return None
        return document

    def revisions(self, strategy_ref: str) -> list[dict]:
        documents = self._find({"kind": "strategy_revision", "strategy_ref": strategy_ref})
        return [dict(doc.get("payload") or {}) for doc in documents]

    def revision(self, revision_ref: str) -> dict | None:
        import json

        try:
            _, body = self.store._request("GET", revision_ref)
        except Exception:
            return None
        document = json.loads(body)
        return document if document.get("kind") == "strategy_revision" else None
