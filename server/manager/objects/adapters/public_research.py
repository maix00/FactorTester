"""Resolve persisted public-research object files for 7997 origins."""

from __future__ import annotations

from pathlib import Path

from server.manager.objects.references import split_research_object_id
from tools.cli.release.research_reporting.public_research.object_store import (
    PublicResearchObjectStore,
)


class PublicResearchOriginAdapter:
    def __init__(self, store: PublicResearchObjectStore) -> None:
        self.store = store

    def __call__(self, transfer) -> Path:
        publication_id, item_id = split_research_object_id(transfer.object_id)
        principal = str(transfer.principal or "").strip()
        viewer = None if principal == "__public_jobs__" else principal or None
        value = self.store.resolve(
            publication_id,
            str(transfer.object_kind),
            item_id,
            viewer,
        )
        if value.size_bytes != int(transfer.expected_size):
            raise RuntimeError("research object size changed after authorization")
        if value.content_hash != str(transfer.expected_sha256).lower():
            raise RuntimeError("research object hash changed after authorization")
        return value.path


__all__ = ["PublicResearchOriginAdapter"]
