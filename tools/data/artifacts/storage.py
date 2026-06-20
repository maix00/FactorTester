"""Provider-scoped storage paths for local and derived market data."""

from __future__ import annotations

import os
import re
from pathlib import Path

from scripts.data_dir import DATA_DIR, load_runtime_settings


def _provider_token(provider: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", provider.upper()).strip("_")


def source_data_root(provider: str, *, default: str | Path | None = None) -> Path:
    """Return one provider's source-data root.

    Existing providers may inject their current root as ``default`` while new
    providers receive an isolated directory automatically.
    """
    configured = os.environ.get(f"GTHT_SOURCE_DATA_DIR_{_provider_token(provider)}")
    if configured:
        return Path(configured).expanduser().resolve()
    settings_dirs = load_runtime_settings().get("source_data_dirs") or {}
    if isinstance(settings_dirs, dict) and settings_dirs.get(provider):
        return Path(settings_dirs[provider]).expanduser().resolve()
    if default is not None:
        return Path(default).expanduser().resolve()
    return Path(DATA_DIR).resolve() / "sources" / provider


def artifact_root(provider: str) -> Path:
    configured = os.environ.get(f"GTHT_ARTIFACT_DIR_{_provider_token(provider)}")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(DATA_DIR).resolve() / "derived_artifacts" / provider


def artifact_path(provider: str, filename: str) -> Path:
    return artifact_root(provider) / filename
