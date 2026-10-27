"""Optional Nautilus feed contract for source-owned adapters.

Only metadata and a loader protocol are defined here. Importing this module
does not load Nautilus, TradeResearch internals, plugins or market data.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class NautilusAdapterContract:
    """Source-owned declaration of one verified Nautilus feed adapter.

    The source owns its physical schema and time semantics. The bridge only
    compares this declaration with the catalog projection before admitting it.
    """

    member_key: str
    adapter_id: str
    frequency: str
    sampling_mode: str
    data_kind: str
    market_depth: str
    delivery_mode: str
    timezone: str
    layout: str
    naming_scheme: str
    required_time_columns: tuple[tuple[str, str], ...]
    required_data_columns: tuple[tuple[str, str], ...]
    clock_policy: str
    product_scope: str
    instrument_scope: str = "unspecified"
    bar_time_semantics: str = "unspecified"
    raw_timestamp_unit: str = "unspecified"
    supported_book_types: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CatalogMemberRef:
    """One staged contract catalog with explicit source and product identity."""

    authority: str
    bundle_id: str
    member_id: str
    product_ref: str
    source_product_ref: str
    contract_uid: str
    catalog_dir: Path
    bar_type: str
    source_revision: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "authority", "bundle_id", "member_id", "product_ref",
            "source_product_ref", "contract_uid", "bar_type",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"catalog member {name} must be a non-empty string")
        if not isinstance(self.catalog_dir, Path):
            raise TypeError("catalog_dir must be a Path")
        revision = self.source_revision
        if revision is not None and (
            not isinstance(revision, str) or not revision.strip()
        ):
            raise ValueError("source_revision must be a non-empty string or None")


@dataclass(frozen=True, slots=True)
class CatalogSet:
    """Explicit multi-contract staging result; never silently drops a contract."""

    refs: tuple[CatalogMemberRef, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.refs, tuple):
            raise TypeError("CatalogSet.refs must be a tuple")
        if any(not isinstance(item, CatalogMemberRef) for item in self.refs):
            raise TypeError("CatalogSet.refs contains a non-CatalogMemberRef")
        identities = [
            (item.authority, item.bundle_id, item.member_id,
             item.source_product_ref, item.contract_uid, item.bar_type)
            for item in self.refs
        ]
        if len(set(identities)) != len(identities):
            raise ValueError("duplicate catalog member reference")

    def products(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(item.product_ref for item in self.refs))

    def by_product(self, product_ref: str) -> tuple[CatalogMemberRef, ...]:
        return tuple(item for item in self.refs if item.product_ref == product_ref)


@dataclass(frozen=True, slots=True)
class CatalogStagingRequest:
    """One immutable set of source contract references to stage."""

    paths: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.paths, tuple):
            raise TypeError("catalog staging paths must be a tuple")
        if not self.paths or any(not isinstance(path, str) or not path for path in self.paths):
            raise ValueError("catalog staging paths must be non-empty strings")


@dataclass(frozen=True, slots=True)
class CatalogLoadRequest:
    """Immutable, bounded request handed to a source-owned catalog loader."""

    source_key: str
    frequency: str
    related_members: tuple[str, ...]
    staging_requests: tuple[CatalogStagingRequest, ...]
    start_utc: str
    end_utc: str
    start_ns: int
    end_ns: int
    target_root: Path

    def __post_init__(self) -> None:
        if not self.source_key or not self.frequency:
            raise ValueError("catalog source and frequency are required")
        if self.start_ns > self.end_ns:
            raise ValueError("catalog range ends before its start")


# The loader is source-owned; no engine or platform domain objects cross this
# boundary. Paths identify the output catalog, never a centrally guessed input.
class NautilusCatalogLoader(Protocol):
    def __call__(self, request: CatalogLoadRequest) -> dict[str, dict[str, str]]: ...


__all__ = [
    "CatalogMemberRef",
    "CatalogSet",
    "CatalogLoadRequest",
    "CatalogStagingRequest",
    "NautilusAdapterContract",
    "NautilusCatalogLoader",
]
