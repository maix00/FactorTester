"""Project the Apple String Catalog to the Manager Web client."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


SUPPORTED_LOCALES = {"zh-Hans", "en"}
SHARED_CATALOG_PATH = (
    Path(__file__).resolve().parents[3]
    / "apple/Resources/Shared/Localizable.xcstrings"
)


def preferred_locale(accept_language: object) -> str:
    """Select a supported locale from an HTTP ``Accept-Language`` value."""
    weighted: list[tuple[float, int, str]] = []
    for index, raw_item in enumerate(str(accept_language or "").split(",")):
        item, *parameters = raw_item.strip().split(";")
        quality = 1.0
        for parameter in parameters:
            name, separator, value = parameter.strip().partition("=")
            if separator and name.lower() == "q":
                try:
                    quality = float(value)
                except ValueError:
                    quality = 0.0
        weighted.append((-quality, index, item.lower()))
    for _quality, _index, language in sorted(weighted):
        if language == "zh-hans" or language.startswith("zh"):
            return "zh-Hans"
        if language == "en" or language.startswith("en-"):
            return "en"
    return "zh-Hans"


@lru_cache(maxsize=len(SUPPORTED_LOCALES))
def shared_localization(locale: str) -> dict[str, str]:
    """Return one cached locale from the Apple/Web shared string catalog."""
    payload = web_localization(SHARED_CATALOG_PATH, locale)
    return dict(payload["strings"])


def page_localization(accept_language: object) -> tuple[str, dict[str, str]]:
    """Return locale and strings for dependency-free public HTML pages."""
    locale = preferred_locale(accept_language)
    try:
        return locale, shared_localization(locale)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        # Authentication must remain available in a minimal server package.
        # Catalog-backed deployments get the selected translation; a package
        # missing the optional catalog safely falls back to the Chinese keys.
        return locale, {}


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
