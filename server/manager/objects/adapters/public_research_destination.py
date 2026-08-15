"""Persist research-object uploads after 7997 integrity verification."""

from __future__ import annotations

from pathlib import Path

from server.manager.objects.references import split_research_object_id
from server.manager.objects.models import TransferObjectKind
from tools.cli.release.research_reporting.public_research.object_store import (
    PublicResearchObjectStore,
)


class PublicResearchDestinationAdapter:
    """Promote a verified staging file into the source Manager publication."""

    def __init__(self, store: PublicResearchObjectStore) -> None:
        self.store = store

    def __call__(self, context, staged_path: Path) -> Path:
        if str(context.transfer.object_kind) not in {
            TransferObjectKind.RESEARCH_ASSET.value,
            TransferObjectKind.RESEARCH_ATTACHMENT.value,
            TransferObjectKind.RESEARCH_LOCAL_RESOURCE.value,
        }:
            return staged_path
        publication_id, item_id = split_research_object_id(
            context.transfer.object_id,
        )
        return self.store.store_from_file(
            publication_id,
            str(context.transfer.object_kind),
            item_id,
            staged_path,
            owner_ref=str(context.transfer.principal or ""),
            expected_size=context.transfer.expected_size,
            expected_sha256=context.transfer.expected_sha256,
        )


__all__ = ["PublicResearchDestinationAdapter"]
