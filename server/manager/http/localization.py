"""Project the Apple String Catalog to the Manager Web client."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


SUPPORTED_LOCALES = {"zh-Hans", "en"}


def web_localization(catalog_path: Path, locale: str) -> dict[str, Any]:
    selected = locale if locale in SUPPORTED_LOCALES else "zh-Hans"
    value = json.loads(catalog_path.read_text(encoding="utf-8"))
    strings = value.get("strings")
    if not isinstance(strings, dict):
        raise ValueError("localization catalog is invalid")
    result: dict[str, str] = {}
    for key, entry in strings.items():
        if not isinstance(entry, dict):
            continue
        localizations = entry.get("localizations")
        if not isinstance(localizations, dict):
            continue
        localized = localizations.get(selected)
        if not isinstance(localized, dict):
            continue
        unit = localized.get("stringUnit")
        translated = unit.get("value") if isinstance(unit, dict) else None
        if isinstance(translated, str) and translated:
            result[str(key)] = translated
    return {
        "schema_version": 1,
        "locale": selected,
        "strings": result,
    }
