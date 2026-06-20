"""Cross-platform contract parquet filename handling."""

from __future__ import annotations

from pathlib import Path


def portable_contract_filename(alias: str, suffix: str = ".parquet") -> str:
    """Return the Windows-safe filename used for newly generated data."""
    return f"{str(alias).replace('|', '_')}{suffix}"


def legacy_contract_filename(alias: str, suffix: str = ".parquet") -> str:
    return f"{alias}{suffix}"


def contract_parquet_candidates(folder: str | Path, alias: str) -> tuple[Path, ...]:
    root = Path(folder)
    portable = root / portable_contract_filename(alias)
    legacy = root / legacy_contract_filename(alias)
    return (portable,) if portable == legacy else (portable, legacy)


def resolve_contract_parquet_path(folder: str | Path, alias: str) -> Path:
    """Prefer portable data, then legacy macOS data; return portable path if absent."""
    candidates = contract_parquet_candidates(folder, alias)
    return next((path for path in candidates if path.is_file()), candidates[0])


def contract_alias_from_path(path: str | Path) -> str:
    stem = Path(path).stem
    return stem if "|" in stem else stem.replace("_", "|")
