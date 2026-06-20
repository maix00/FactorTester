"""Cross-platform contract parquet filename handling."""

from __future__ import annotations

from pathlib import Path


def portable_contract_filename(alias: str, suffix: str = ".parquet") -> str:
    """Return the Windows-safe filename used for newly generated data."""
    return f"{str(alias).replace('|', '_')}{suffix}"


def resolve_contract_parquet_path(folder: str | Path, alias: str) -> Path:
    """Return the canonical cross-platform path for a contract."""
    return Path(folder) / portable_contract_filename(alias)


def contract_alias_from_path(path: str | Path) -> str:
    return Path(path).stem.replace("_", "|")
