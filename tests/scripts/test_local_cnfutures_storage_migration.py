import json
from pathlib import Path

from sources.LocalCNFutures.scripts import migrate_storage


def test_migration_is_dry_run_by_default_and_excludes_unrelated_data(monkeypatch, tmp_path: Path):
    source = tmp_path / "data"
    target = source / "sources" / "LocalCNFutures"
    source.mkdir()
    (source / "data_dayk.parquet").write_bytes(b"dayk")
    (source / "Factors").mkdir()
    (source / "Factors" / "factor.parquet").write_bytes(b"factor")
    monkeypatch.setattr(migrate_storage, "artifact_root", lambda provider: source / "derived" / provider)

    result = migrate_storage.migrate(
        source_root=source,
        target_root=target,
        execute=False,
        remove_source=False,
    )

    assert result["dry_run"] is True
    assert not target.exists()
    planned = {Path(item["source"]).name for item in result["assets"]}
    assert "data_dayk.parquet" in planned
    assert "Factors" not in planned


def test_migration_copies_verifies_activates_and_archives_old_curve(monkeypatch, tmp_path: Path):
    source = tmp_path / "data"
    target = source / "sources" / "LocalCNFutures"
    artifact_dir = source / "derived_artifacts" / "LocalCNFutures"
    source.mkdir()
    (source / "main_dayk").mkdir()
    (source / "main_dayk" / "A.DCE.parquet").write_bytes(b"main")
    (source / "roller_info.parquet").write_bytes(b"roller")
    (source / "cn_futures_term_structure.parquet").write_bytes(b"invalid-curve")
    monkeypatch.setattr(migrate_storage, "artifact_root", lambda provider: artifact_dir)
    monkeypatch.setattr(migrate_storage, "DATA_DIR", str(source))
    monkeypatch.setattr(migrate_storage, "get_feat_root", lambda: str(tmp_path / "FactorTester"))

    result = migrate_storage.migrate(
        source_root=source,
        target_root=target,
        execute=True,
        remove_source=False,
    )

    assert (target / "main_dayk" / "A.DCE.parquet").read_bytes() == b"main"
    assert (artifact_dir / "roller_info.parquet").read_bytes() == b"roller"
    assert (artifact_dir / "legacy" / "term_structure-v1-invalid.parquet").read_bytes() == b"invalid-curve"
    assert (target / "migration-manifest.json").is_file()
    settings = json.loads((tmp_path / ".settings").read_text(encoding="utf-8"))
    assert settings["source_data_dirs"]["LocalCNFutures"] == str(target.resolve())
    assert (source / "roller_info.parquet").exists()
