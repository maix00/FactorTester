#!/usr/bin/env python3
"""Audit the shared SwiftUI String Catalog contract.

The client keeps one ``Localizable.xcstrings`` source of truth. This check
ensures every visible literal and explicit ``L10n`` key is present, every
supported locale has a translation, and dynamic strings have a matching
format key.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "Sources"
CATALOG = ROOT / "Resources" / "Shared" / "Localizable.xcstrings"
LOCALES = ("en", "zh-Hans")
CALLS = (
    "Text", "Label", "Button", "Section", "Menu", "Picker",
    "navigationTitle", "alert", "confirmationDialog", "TextField",
    "SecureField", "Toggle", "GroupBox", "ProgressView", "LabeledContent",
    "DisclosureGroup", "TableColumn", "help", "LocalizedStringKey",
)
CALL_PATTERN = re.compile(
    r"\b(?:" + "|".join(CALLS) + r")\s*\(\s*\"((?:\\.|[^\"\\])*)\""
)
SETTINGS_POSITIONAL_PATTERN = re.compile(
    r"\b(?:SettingsSectionCard|SettingsRefreshButton|SettingsCard)"
    r"\s*\(\s*\"((?:\\.|[^\"\\])*)\""
)
SETTINGS_FIELD_PATTERN = re.compile(
    r"\b(?:SettingsPageShell|SettingsPageHeader|SettingsRow)\s*\([^)]*?"
    r"\b(?:title|subtitle|description)\s*:\s*\"((?:\\.|[^\"\\])*)\"",
    re.DOTALL,
)
NAMED_DISPLAY_FIELD_PATTERN = re.compile(
    r"\b(?:SettingsPageShell|SettingsPageHeader|SettingsSectionCard|SettingsRow|"
    r"DashboardShortcutCard)\s*\([^)]*?\b(?:title|subtitle|description)\s*:\s*"
    r"\"((?:\\.|[^\"\\])*)\"",
    re.DOTALL,
)
DISPLAY_TEXT_VALUE_PATTERN = re.compile(
    r"\bSettingsDisplayText\s*\(\s*\"((?:\\.|[^\"\\])*)\""
)
NAMED_ARGUMENT_PATTERN = re.compile(
    r"\b(?:title|subtitle|description)\s*:\s*\"((?:\\.|[^\"\\])*)\""
)
LABEL_ARGUMENT_PATTERN = re.compile(
    r"\blabel\s*:\s*\"((?:\\.|[^\"\\])*)\""
)
PRESENTATION_GROUP_PATTERN = re.compile(
    r"\b(?:referenceGroup|changeGroup|treeLegend|statusLegend)\s*\(\s*"
    r"\"((?:\\.|[^\"\\])*)\""
)
L10N_PATTERN = re.compile(
    r"L10n\.(?:text|format)\(\s*\"((?:\\.|[^\"\\])*)\""
)
RESOURCE_PATTERN = re.compile(
    r"L10n\.resource\(\s*\"((?:\\.|[^\"\\])*)\""
)
DYNAMIC_RETURN_PATTERN = re.compile(
    r"\breturn\s+\"((?:\\.|[^\"\\])*)\""
)
HIGH_RISK_RAW_DISPLAY_PATTERNS = (
    re.compile(r"\bText\(\s*detail\.status\s*\)"),
    re.compile(r"\bText\(\s*row\.(?:materiality|change|currentStatus)\s*\)"),
    re.compile(r"\bTextField\(\s*L10n\.resource\("),
)


def catalog_keys() -> tuple[set[str], list[str]]:
    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate String Catalog key: {key}")
            result[key] = value
        return result

    catalog = json.loads(
        CATALOG.read_text(encoding="utf-8"),
        object_pairs_hook=reject_duplicate_keys,
    )
    strings = catalog.get("strings", {})
    if not isinstance(strings, dict):
        raise ValueError(f"invalid String Catalog strings object: {CATALOG}")
    issues: list[str] = []
    for key, entry in strings.items():
        localizations = entry.get("localizations", {})
        for locale in LOCALES:
            localization = localizations.get(locale)
            if not isinstance(localization, dict):
                issues.append(f"missing localization {key} [{locale}]")
                continue
            unit = localization.get("stringUnit", {})
            if not unit.get("value"):
                issues.append(f"empty localization {key} [{locale}]")
    return set(strings), issues


def source_keys() -> tuple[set[str], set[str], set[str], dict[str, set[str]]]:
    visible: set[str] = set()
    interpolated: set[str] = set()
    explicit: set[str] = set()
    by_module: dict[str, set[str]] = {}
    for path in SOURCE_ROOT.rglob("*.swift"):
        source = path.read_text(encoding="utf-8")
        relative = path.relative_to(SOURCE_ROOT)
        module = "/".join(relative.parts[:-1]) or "Root"
        module_keys = by_module.setdefault(module, set())
        for match in CALL_PATTERN.finditer(source):
            key = match.group(1)
            if key and "\\(" in key:
                interpolated.add(key)
                continue
            if key and key not in {"·", "•"}:
                visible.add(key)
                module_keys.add(key)
        for pattern in (
            SETTINGS_POSITIONAL_PATTERN,
            SETTINGS_FIELD_PATTERN,
            NAMED_DISPLAY_FIELD_PATTERN,
            DISPLAY_TEXT_VALUE_PATTERN,
            NAMED_ARGUMENT_PATTERN,
            LABEL_ARGUMENT_PATTERN,
            PRESENTATION_GROUP_PATTERN,
        ):
            for match in pattern.finditer(source):
                key = match.group(1)
                if key and "\\(" not in key:
                    visible.add(key)
                    module_keys.add(key)
        explicit.update(match.group(1) for match in L10N_PATTERN.finditer(source))
        explicit.update(match.group(1) for match in RESOURCE_PATTERN.finditer(source))
    return visible, explicit, interpolated, by_module


def dynamic_contract_issues(catalog: set[str]) -> tuple[list[str], int]:
    """Check String-returning presentation helpers and known raw displays.

    SwiftUI extracts literal ``Text`` calls automatically, but a helper that
    returns a ``String`` bypasses that extraction. Chinese UI strings in a
    presentation helper must therefore still be catalog keys.
    """
    failures: list[str] = []
    dynamic_count = 0
    for path in SOURCE_ROOT.rglob("*.swift"):
        source = path.read_text(encoding="utf-8")
        for match in DYNAMIC_RETURN_PATTERN.finditer(source):
            key = match.group(1)
            if not re.search(r"[\u4e00-\u9fff]", key):
                continue
            dynamic_count += 1
            if key not in catalog:
                line = source.count("\n", 0, match.start()) + 1
                failures.append(
                    f"dynamic return missing catalog key "
                    f"{path.relative_to(ROOT)}:{line}: {key}"
                )
        for pattern in HIGH_RISK_RAW_DISPLAY_PATTERNS:
            if pattern.search(source):
                failures.append(
                    f"raw dynamic display is not localized in "
                    f"{path.relative_to(ROOT)}"
                )
    return failures, dynamic_count


def interpolation_shape(value: str) -> tuple[str, str] | None:
    parts = re.split(r"\\\\\([^)]*\\\\\)", value)
    if len(parts) < 2:
        return None
    prefix, suffix = parts[0], parts[-1]
    if not prefix and not suffix:
        return None
    return prefix, suffix


def has_interpolation_key(catalog: set[str], source: str) -> bool:
    shape = interpolation_shape(source)
    if shape is None:
        return True
    prefix, suffix = shape
    return any(key.startswith(prefix) and key.endswith(suffix) for key in catalog)


def main() -> int:
    catalogs, catalog_issues = catalog_keys()
    visible, explicit, interpolated, by_module = source_keys()
    failures = list(catalog_issues)
    dynamic_failures, dynamic_count = dynamic_contract_issues(catalogs)
    failures.extend(dynamic_failures)
    for key in sorted(visible | explicit):
        if key not in catalogs:
            failures.append(f"catalog: missing {key}")
    for source in sorted(interpolated):
        if not has_interpolation_key(catalogs, source):
            failures.append(f"catalog: missing interpolation key for {source}")
    print(
        f"localization audit: {len(visible)} visible literals, "
        f"{len(interpolated)} interpolated literals, "
        f"{len(explicit)} explicit keys, "
        f"{dynamic_count} dynamic localized returns, "
        f"{len(catalogs)} keys in Localizable.xcstrings"
    )
    for module, keys in sorted(by_module.items()):
        missing = sum(key not in catalogs for key in keys)
        state = "PASS" if missing == 0 else f"FAIL ({missing} missing)"
        print(f"  {state:<14} {module}: {len(keys)} visible keys")
    if failures:
        for failure in failures:
            print(failure, file=sys.stderr)
        return 1
    print("localization audit: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
