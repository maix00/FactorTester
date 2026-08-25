"""One-time migration from source-embedded factor metadata to SQLite rows."""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

import settings as Settings

from tools.data.sqlite.factor_source_store import (
    METADATA_TABLE,
    SOURCE_TABLE,
    normalize_factor_source_code,
)


def _strip_legacy_display_metadata(source_code: str) -> str:
    """Rewrite the legacy source shape only during the explicit migration."""
    normalized = normalize_factor_source_code(source_code or "")
    lines: list[str] = []
    in_description = False
    for line in normalized.splitlines():
        if in_description:
            if '"""' in line or "'''" in line:
                in_description = False
            continue
        if re.match(r"^\s*description\s*=\s*(\"\"\"|''')", line):
            if line.count('"""') + line.count("'''") < 2:
                in_description = True
            continue
        if re.match(r"^\s*(desc|category)\s*=\s*", line):
            continue
        if line.strip().startswith(("# -*- coding:", "# Custom Factor:")):
            continue
        lines.append(line)
    value = "\n".join(lines).strip("\n")
    return f"{value}\n" if value else ""


def _legacy_display_metadata(source_code: str) -> dict[str, str]:
    """Parse display fields only inside the one-time migration."""
    result = {"chinese_name": "", "description": "", "category": ""}
    match = re.search(
        r"^\s*desc\s*=\s*['\"]([^'\"]*)['\"]", source_code, re.MULTILINE,
    )
    if match:
        result["chinese_name"] = match.group(1)
    match = re.search(
        r"^\s*description\s*=\s*(\"\"\"|''')(.*?)\1",
        source_code,
        re.MULTILINE | re.DOTALL,
    ) or re.search(
        r"^\s*description\s*=\s*['\"]([^'\"]*)['\"]",
        source_code,
        re.MULTILINE,
    )
    if match:
        result["description"] = match.group(2) if match.lastindex == 2 else match.group(1)
    match = re.search(
        r"^\s*category\s*=\s*['\"]([^'\"]*)['\"]", source_code, re.MULTILINE,
    )
    if match:
        result["category"] = match.group(1)
    return result


def _upgrade_legacy_formula_source(factor_id: str, source_code: str) -> str:
    """Replace known pre-fingerprint formula nodes during explicit migration."""
    if factor_id != "VlYZ" or "class _DynamicWeight(FactorExpr):" not in source_code:
        return source_code
    value = source_code.replace(
        "from tools.factors.FactorExpr import FactorExpr",
        "from tools.factors.FactorExpr import window_bars",
    )
    old = (
        "        yz_var = (sig_o2 + _DynamicWeight(N) * sig_c2 + "
        "(1.0 - _DynamicWeight(N)) * sig_rs2).as_intermediate('SIG_YZ2')"
    )
    new = (
        "        n = window_bars(N).max(2.0)\n"
        "        weight = 0.34 / (1.34 + (n + 1.0) / (n - 1.0))\n"
        "        yz_var = (sig_o2 + weight * sig_c2 + "
        "(1.0 - weight) * sig_rs2).as_intermediate('SIG_YZ2')"
    )
    if old not in value:
        raise ValueError("legacy VlYZ source does not match the explicit migration")
    value = value.replace(old, new)
    value, replaced = re.subn(
        r"\nclass _DynamicWeight\(FactorExpr\):.*?(?=\nif __name__ ==)",
        "\n",
        value,
        flags=re.DOTALL,
    )
    if replaced != 1:
        raise ValueError("legacy VlYZ helper could not be removed")
    return value


def migrate_factor_source_metadata(database: str | Path) -> dict[str, int]:
    """Migrate all existing source rows and never run implicitly at import."""
    path = Path(database).expanduser().resolve()
    if not path.exists():
        return {"source_rows": 0, "metadata_rows": 0, "rewritten_sources": 0}
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if SOURCE_TABLE not in tables:
            return {"source_rows": 0, "metadata_rows": 0, "rewritten_sources": 0}
        connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {METADATA_TABLE} (
                source_kind TEXT NOT NULL,
                owner_username TEXT NOT NULL DEFAULT '',
                factor_id TEXT NOT NULL,
                chinese_name TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT '',
                updated_at REAL NOT NULL,
                PRIMARY KEY (source_kind, owner_username, factor_id)
            )
            """
        )
        rows = connection.execute(
            f"""
            SELECT source_kind, owner_username, factor_id, source_code, updated_at
            FROM {SOURCE_TABLE}
            """
        ).fetchall()
        metadata_rows = 0
        rewritten_sources = 0
        for row in rows:
            source = str(row["source_code"] or "")
            parsed = _legacy_display_metadata(source)
            inserted = connection.execute(
                f"""
                INSERT OR IGNORE INTO {METADATA_TABLE} (
                    source_kind, owner_username, factor_id,
                    chinese_name, description, category, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["source_kind"],
                    row["owner_username"],
                    row["factor_id"],
                    str(parsed.get("chinese_name") or ""),
                    str(parsed.get("description") or ""),
                    str(parsed.get("category") or ""),
                    float(row["updated_at"] or 0.0),
                ),
            ).rowcount
            metadata_rows += int(inserted or 0)
            canonical = _strip_legacy_display_metadata(
                _upgrade_legacy_formula_source(str(row["factor_id"]), source)
            )
            if canonical != source:
                connection.execute(
                    f"""
                    UPDATE {SOURCE_TABLE}
                    SET source_code = ?
                    WHERE source_kind = ? AND owner_username = ? AND factor_id = ?
                    """,
                    (
                        canonical,
                        row["source_kind"],
                        row["owner_username"],
                        row["factor_id"],
                    ),
                )
                rewritten_sources += 1
        return {
            "source_rows": len(rows),
            "metadata_rows": metadata_rows,
            "rewritten_sources": rewritten_sources,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default=str(Settings.CACHE_DB_PATH))
    arguments = parser.parse_args(argv)
    report: dict[str, Any] = migrate_factor_source_metadata(arguments.database)
    for key, value in report.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
