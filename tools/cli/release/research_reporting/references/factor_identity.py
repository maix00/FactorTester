"""CLI boundary for the local batch FactorFamily alias validator."""

from __future__ import annotations

from pathlib import Path

from tools.factors.alias_validator import canonical_factor_identity


def validate_canonical_factor_identity(
    *,
    source_file: Path,
    identity: str,
    object_kind: str,
    blob_hash: str,
) -> str:
    """Reject new immutable references that use a non-canonical alias."""
    canonical = canonical_factor_identity(
        source_file=source_file,
        identity=str(identity),
        object_kind=object_kind,
        blob_hash=blob_hash,
    )
    if identity != canonical:
        raise ValueError(
            f"Non-canonical factor identity {identity!r}; expected {canonical!r}"
        )
    return canonical
