from __future__ import annotations

import sqlite3

import settings as Settings
from scripts.import_user_factor_directory_once import import_user_factor_directory_once


def test_import_user_factor_directory_once_imports_local_files(monkeypatch, tmp_path):
    sqlite_path = tmp_path / "cache" / "localdata" / "unifieddata.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DIR", sqlite_path.parent)
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", sqlite_path)

    username = "default$alice@1"
    source_root = tmp_path / "factor-root"
    custom_dir = source_root / "custom_factors"
    custom_dir.mkdir(parents=True)
    (custom_dir / "ImportedFactor.py").write_text("class ImportedFactor(FactorFamily):\n    pass\n", encoding="utf-8")

    result = import_user_factor_directory_once(username, str(source_root))
    assert result["imported_count"] == 1
    assert result["imported_ids"] == ["ImportedFactor"]

    with sqlite3.connect(sqlite_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT source_code
            FROM factor_family_sources
            WHERE source_kind = 'custom' AND owner_username = ? AND factor_id = 'ImportedFactor'
            """,
            (username,),
        ).fetchone()
        assert row is not None
        assert row["source_code"] == "class ImportedFactor(FactorFamily):\n    pass\n"
