from __future__ import annotations

import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from tools.cli.local_paths import documents_root, select_existing_root
from tools.cli.release import local_path_migration as migration


@pytest.mark.parametrize("kind", ["cli", "documents"])
def test_move_and_rollback_keep_same_inode_and_legacy_references(tmp_path, kind):
    source, target = migration._roots(kind, tmp_path)
    source.mkdir(parents=True)
    secret = source / "session"
    secret.write_bytes(b"private-test-fixture")
    secret.chmod(0o600)
    inode = source.stat().st_ino
    file_inode = secret.stat().st_ino
    plan = migration.plan(kind, home=tmp_path)
    receipt = tmp_path / "receipts" / f"{kind}.jsonl"
    result = migration.apply(kind, expected_sha256=plan["sha256"], receipt=receipt,
                             quiesced=True, home=tmp_path)
    assert result["status"] == "applied"
    assert source.is_symlink() and os.path.samefile(source, target)
    assert target.stat().st_ino == inode and (target / "session").stat().st_ino == file_inode
    assert (target / "session").read_bytes() == b"private-test-fixture"
    assert (target / "session").stat().st_mode & 0o777 == 0o600
    assert receipt.stat().st_mode & 0o777 == 0o600
    assert b"private-test-fixture" not in receipt.read_bytes()
    assert migration.plan(kind, home=tmp_path)["state"] == "already_migrated"
    assert migration.rollback(receipt=receipt, quiesced=True, home=tmp_path)["status"] == "rolled_back"
    assert target.is_symlink() and os.path.samefile(source, target)
    assert source.stat().st_ino == inode and secret.stat().st_ino == file_inode
    assert migration.rollback(receipt=receipt, quiesced=True, home=tmp_path)["status"] == "already_rolled_back"


def test_conflict_drift_and_missing_quiescence_are_rejected(tmp_path):
    source, target = migration._roots("cli", tmp_path)
    source.mkdir()
    (source / "config").write_text("before")
    reviewed = migration.plan("cli", home=tmp_path)
    receipt = tmp_path / "receipt"
    with pytest.raises(ValueError, match="close clients"):
        migration.apply("cli", expected_sha256=reviewed["sha256"], receipt=receipt,
                        quiesced=False, home=tmp_path)
    (source / "config").write_text("changed value")
    with pytest.raises(ValueError, match="plan changed"):
        migration.apply("cli", expected_sha256=reviewed["sha256"], receipt=receipt,
                        quiesced=True, home=tmp_path)
    target.mkdir()
    assert migration.plan("cli", home=tmp_path)["state"] == "conflict"
    assert (source / "config").read_text() == "changed value"
    assert not receipt.exists()


def test_interrupted_move_is_recovered_with_original_inode(tmp_path, monkeypatch):
    source, target = migration._roots("documents", tmp_path)
    source.mkdir(parents=True)
    (source / "report").write_text("data")
    inode = source.stat().st_ino
    reviewed = migration.plan("documents", home=tmp_path)
    receipt = tmp_path / "receipt"
    write = migration._write_receipt
    def interrupted(path, value, *, create):
        if value["event"] == "moved":
            raise OSError("interrupted")
        return write(path, value, create=create)
    monkeypatch.setattr(migration, "_write_receipt", interrupted)
    with pytest.raises(OSError, match="interrupted"):
        migration.apply("documents", expected_sha256=reviewed["sha256"], receipt=receipt,
                        quiesced=True, home=tmp_path)
    assert not source.exists() and target.stat().st_ino == inode
    monkeypatch.setattr(migration, "_write_receipt", write)
    assert migration.recover(receipt=receipt, quiesced=True, home=tmp_path)["status"] == "applied"
    assert source.is_symlink() and os.path.samefile(source, target)
    assert migration.rollback(receipt=receipt, quiesced=True, home=tmp_path)["status"] == "rolled_back"


def test_late_target_creation_is_not_overwritten(tmp_path, monkeypatch):
    source, target = migration._roots("cli", tmp_path)
    source.mkdir()
    (source / "owner-data").write_text("mine")
    reviewed = migration.plan("cli", home=tmp_path)
    rename = migration._rename_noreplace
    def race(src, dst):
        dst.mkdir()
        (dst / "other-data").write_text("theirs")
        rename(src, dst)
    monkeypatch.setattr(migration, "_rename_noreplace", race)
    with pytest.raises(OSError):
        migration.apply("cli", expected_sha256=reviewed["sha256"], receipt=tmp_path / "receipt",
                        quiesced=True, home=tmp_path)
    assert (source / "owner-data").read_text() == "mine"
    assert (target / "other-data").read_text() == "theirs"


@pytest.mark.parametrize("interruption", ["after_unlink", "after_move"])
def test_interrupted_rollback_is_recovered_without_copy(tmp_path, monkeypatch, interruption):
    source, target = migration._roots("cli", tmp_path)
    source.mkdir()
    (source / "session").write_bytes(b"fixture")
    inode = source.stat().st_ino
    reviewed = migration.plan("cli", home=tmp_path)
    receipt = tmp_path / "receipt"
    migration.apply("cli", expected_sha256=reviewed["sha256"], receipt=receipt,
                    quiesced=True, home=tmp_path)
    if interruption == "after_unlink":
        rename = migration._rename_noreplace
        monkeypatch.setattr(migration, "_rename_noreplace", lambda *_: (_ for _ in ()).throw(SystemExit()))
    else:
        symlink = os.symlink
        monkeypatch.setattr(os, "symlink", lambda *_, **__: (_ for _ in ()).throw(SystemExit()))
    with pytest.raises(SystemExit):
        migration.rollback(receipt=receipt, quiesced=True, home=tmp_path)
    if interruption == "after_unlink":
        monkeypatch.setattr(migration, "_rename_noreplace", rename)
    else:
        monkeypatch.setattr(os, "symlink", symlink)
    assert migration.recover(receipt=receipt, quiesced=True, home=tmp_path)["status"] == "rolled_back"
    assert source.stat().st_ino == inode
    assert target.is_symlink() and os.path.samefile(source, target)


def test_documents_root_choices_and_conflicts(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    source, target = migration._roots("documents", tmp_path)
    assert documents_root() == target
    source.mkdir(parents=True)
    assert documents_root() == source
    target.symlink_to(source, target_is_directory=True)
    assert documents_root() == target
    target.unlink()
    target.mkdir()
    with pytest.raises(RuntimeError, match="conflict"):
        documents_root()


def test_broken_alias_cannot_redirect_to_new_empty_authority(tmp_path):
    current = tmp_path / "current"
    legacy = tmp_path / "legacy"
    legacy.symlink_to(tmp_path / "missing", target_is_directory=True)
    with pytest.raises(RuntimeError, match="invalid"):
        select_existing_root(current, legacy, label="test")


def test_cli_plan_is_read_only(tmp_path, monkeypatch):
    from tools.cli.app import cli
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    result = CliRunner().invoke(cli, ["client", "local-paths", "plan", "--kind", "documents"])
    assert result.exit_code == 0, result.output
    assert '"state": "absent"' in result.output
    assert not (tmp_path / "Documents").exists()
