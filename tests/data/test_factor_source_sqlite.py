from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import settings as Settings


def _load_storage_module():
    storage_path = Path(__file__).resolve().parents[2] / "tools" / "data" / "factor_workspace" / "storage.py"
    spec = importlib.util.spec_from_file_location("test_factor_storage_module_db", storage_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_factor_source_sqlite_roundtrip(monkeypatch, tmp_path):
    sqlite_path = tmp_path / "cache" / "localdata" / "unifieddata.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DIR", sqlite_path.parent)
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", sqlite_path)

    fallback_root = tmp_path / "fallback-user-root"
    factor_storage = _load_storage_module()
    monkeypatch.setattr(factor_storage, "WORKSPACE_ROOTS_DIR", str(fallback_root))

    username = "default$alice@1"
    factor_id = "DemoFactor"
    source_code = "class DemoFactor(FactorFamily):\n    pass\n"

    monkeypatch.setattr(
        factor_storage,
        "load_factor_source_root",
        lambda _username: str(fallback_root / username),
    )

    factor_storage.save_factor_source(username, factor_id, source_code)
    assert factor_storage.load_factor_source(username, factor_id) == source_code

    mirror_path = fallback_root / username / "custom_factors" / f"{factor_id}.py"
    assert mirror_path.exists()
    assert mirror_path.read_text(encoding="utf-8") == source_code

    mirror_path.unlink()
    assert not mirror_path.exists()
    assert factor_storage.load_factor_source(username, factor_id) == source_code

    with sqlite3.connect(sqlite_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT source_kind, owner_username, factor_id, factor_name, source_code
            FROM factor_family_sources
            WHERE source_kind = 'custom' AND owner_username = ? AND factor_id = ?
            """,
            (username, factor_id),
        ).fetchone()
        assert row is not None
        assert row["factor_name"] == factor_id
        assert row["source_code"] == source_code

    assert factor_storage.rename_factor_source(username, factor_id, "DemoFactorV2")
    assert factor_storage.load_factor_source(username, "DemoFactorV2") == source_code

    with sqlite3.connect(sqlite_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT factor_id, factor_name, source_code
            FROM factor_family_sources
            WHERE source_kind = 'custom' AND owner_username = ? AND factor_id = ?
            """,
            (username, "DemoFactorV2"),
        ).fetchone()
        assert row is not None
        assert row["factor_id"] == "DemoFactorV2"
        assert row["factor_name"] == "DemoFactorV2"
        assert row["source_code"] == source_code

    assert factor_storage.delete_factor_source(username, "DemoFactorV2")
    with sqlite3.connect(sqlite_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM factor_family_sources
            WHERE source_kind = 'custom' AND owner_username = ? AND factor_id = ?
            """,
            (username, "DemoFactorV2"),
        ).fetchone()
        assert row["n"] == 0


def test_factor_source_save_does_not_create_server_workspace_without_configuration(
    monkeypatch, tmp_path,
):
    sqlite_path = tmp_path / "cache" / "localdata" / "unifieddata.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DIR", sqlite_path.parent)
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", sqlite_path)

    fallback_root = tmp_path / "fallback-user-root"
    factor_storage = _load_storage_module()
    monkeypatch.setattr(factor_storage, "WORKSPACE_ROOTS_DIR", str(fallback_root))
    monkeypatch.setattr(factor_storage, "load_factor_source_root", lambda _username: None)

    factor_storage.save_factor_source(
        "default$alice@1", "NoWorkspaceFactor",
        "class NoWorkspaceFactor(FactorFamily):\n    pass\n",
    )

    assert not fallback_root.exists()
    assert factor_storage.load_factor_source(
        "default$alice@1", "NoWorkspaceFactor",
    ) is not None


def test_default_server_factor_workspace_uses_portable_user_layout(
    monkeypatch, tmp_path,
):
    factor_storage = _load_storage_module()
    users_root = tmp_path / "users"
    monkeypatch.setattr(
        factor_storage,
        "WORKSPACE_ROOTS_DIR",
        str(users_root),
    )
    monkeypatch.setattr(
        factor_storage,
        "load_factor_source_root",
        lambda _username: None,
    )

    root = Path(factor_storage.factor_source_root("default$alice@1"))

    assert root == (
        users_root
        / "default$alice@1"
        / "personal-workspace"
        / "factor-library"
    )
    assert root.is_dir()


def test_factor_source_sqlite_normalizes_legacy_import_paths(monkeypatch, tmp_path):
    sqlite_path = tmp_path / "cache" / "localdata" / "unifieddata.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DIR", sqlite_path.parent)
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", sqlite_path)

    fallback_root = tmp_path / "fallback-user-root"
    factor_storage = _load_storage_module()
    monkeypatch.setattr(factor_storage, "WORKSPACE_ROOTS_DIR", str(fallback_root))

    username = "default$alice@1"
    factor_id = "LegacyImportsFactor"
    monkeypatch.setattr(
        factor_storage,
        "load_factor_source_root",
        lambda _username: str(fallback_root / username),
    )
    source_code = (
        "from tools import DataFreq\n"
        "from tools.data import DataProviderProductTS\n"
        "from tools.data.types import normalize_currency, require_product_currency_vector\n"
        "from tools.factors import FactorFamily\n"
        "\n"
        "class LegacyImportsFactor(FactorFamily):\n"
        "    pass\n"
    )

    factor_storage.save_factor_source(username, factor_id, source_code)
    normalized = factor_storage.load_factor_source(username, factor_id)
    assert normalized is not None
    assert "from tools.data.types import DataFreq" in normalized
    assert "from tools.data.providers import DataProviderProductTS" in normalized
    assert "from tools.data.types.currency import normalize_currency, require_product_currency_vector" in normalized
    assert "from tools import DataFreq" not in normalized
    assert "from tools.data import DataProviderProductTS" not in normalized
    assert "from tools.data.types import normalize_currency" not in normalized

    mirror_path = fallback_root / username / "custom_factors" / f"{factor_id}.py"
    assert mirror_path.read_text(encoding="utf-8") == normalized

    with sqlite3.connect(sqlite_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT source_code
            FROM factor_family_sources
            WHERE source_kind = 'custom' AND owner_username = ? AND factor_id = ?
            """,
            (username, factor_id),
        ).fetchone()
        assert row is not None
        assert "from tools.data.providers import DataProviderProductTS" in row["source_code"]


def test_user_factor_load_does_not_import_local_directory(monkeypatch, tmp_path):
    sqlite_path = tmp_path / "cache" / "localdata" / "unifieddata.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DIR", sqlite_path.parent)
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", sqlite_path)

    fallback_root = tmp_path / "fallback-user-root"
    factor_storage = _load_storage_module()
    monkeypatch.setattr(factor_storage, "WORKSPACE_ROOTS_DIR", str(fallback_root))

    username = "default$alice@1"
    factor_id = "LocalOnlyFactor"
    local_dir = fallback_root / username / "custom_factors"
    local_dir.mkdir(parents=True)
    (local_dir / f"{factor_id}.py").write_text("class LocalOnlyFactor(FactorFamily):\n    pass\n", encoding="utf-8")

    assert factor_storage.load_factor_source(username, factor_id) is None

    with sqlite3.connect(sqlite_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM factor_family_sources
            WHERE source_kind = 'custom' AND owner_username = ? AND factor_id = ?
            """,
            (username, factor_id),
        ).fetchone()
        assert row["n"] == 0


def test_public_factor_source_is_registry_only(monkeypatch, tmp_path):
    sqlite_path = tmp_path / "cache" / "localdata" / "unifieddata.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DIR", sqlite_path.parent)
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", sqlite_path)

    factor_storage = _load_storage_module()
    monkeypatch.chdir(tmp_path)
    source_code = "class RegistryOnly(FactorFamily):\n    pass\n"

    factor_storage.save_public_factor_source("RegistryOnly", source_code)

    assert factor_storage.load_public_factor_source("RegistryOnly") == source_code
    assert not (tmp_path / "Factors").exists()
    with sqlite3.connect(sqlite_path) as conn:
        row = conn.execute(
            """
            SELECT source_code
            FROM factor_family_sources
            WHERE source_kind = 'public' AND owner_username = ''
              AND factor_id = 'RegistryOnly'
            """
        ).fetchone()
    assert row is not None
    assert row[0] == source_code
