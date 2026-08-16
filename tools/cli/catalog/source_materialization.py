"""Materialize local source manifests into the embedded client catalog."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from typing import Any, Iterable

from .store import LocalCatalogStore
from tools.cli.local_sources.contracts import LocalSourceManifest


def materialize_local_manifests(
    store: LocalCatalogStore,
    manifests: Iterable[LocalSourceManifest],
) -> dict[str, Any]:
    """Persist source/product identities while keeping local availability."""
    sources = 0
    products = 0
    for manifest in manifests:
        source_id = f"local:{manifest.source_id}"
        status = str(manifest.availability.get("status") or "unavailable")
        source_state = {
            "ready": "active",
            "disabled": "disabled",
        }.get(status, "unavailable")
        content_hash = hashlib.sha256(
            json.dumps(asdict(manifest), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        source = {
            "source_id": source_id,
            "source_kind": "local_bundle",
            "owner_ref": "",
            "class_path": "Product",
            "source_revision": manifest.version,
            "content_hash": content_hash,
            "state": source_state,
        }
        rows = []
        available = set(manifest.availability.get("available_product_refs") or ())
        for product in manifest.products:
            product_ref = f"{source_id}:{product.product_ref}"
            rows.append({
                "product_ref": product_ref,
                "source_id": source_id,
                "class_path": product.class_path,
                "alias": product.alias,
                "display_name": product.display_name,
                "product_kind": product.product_kind,
                "catalog_revision": manifest.version,
                "metadata": {
                    **product.metadata,
                    "local_source_id": manifest.source_id,
                    "manifest_product_ref": product.product_ref,
                    "category_values": product.category_values,
                },
                "state": "active" if source_state == "active" and product.product_ref in available else source_state,
            })
        store.materialize_source(source, rows)
        sources += 1
        products += len(rows)
    return {"sources": sources, "products": products}


__all__ = ["materialize_local_manifests"]
