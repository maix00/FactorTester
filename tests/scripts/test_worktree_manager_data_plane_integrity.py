from __future__ import annotations

import hashlib

import pytest

from server.manager.data_plane.integrity import (
    IntegrityError,
    VerifiedStagingWriter,
    verify_file,
)


def test_verified_staging_writer_atomically_promotes_complete_file(tmp_path) -> None:
    target = tmp_path / "artifact.bin"
    raw = b"abcdef"
    writer = VerifiedStagingWriter(
        target,
        expected_size=len(raw),
        expected_sha256=hashlib.sha256(raw).hexdigest(),
    )

    writer.write(b"abc")
    writer.write(b"def")
    result = writer.finish()

    assert result == target
    assert target.read_bytes() == raw
    assert list(tmp_path.glob(".*.transfer.tmp")) == []


def test_failed_integrity_never_replaces_existing_target(tmp_path) -> None:
    target = tmp_path / "artifact.bin"
    target.write_bytes(b"old")
    writer = VerifiedStagingWriter(
        target,
        expected_size=3,
        expected_sha256=hashlib.sha256(b"new").hexdigest(),
    )
    writer.write(b"bad")

    with pytest.raises(IntegrityError, match="SHA-256"):
        writer.finish()

    assert target.read_bytes() == b"old"
    assert list(tmp_path.glob(".*.transfer.tmp")) == []


def test_resume_reuses_verified_prefix_and_checks_whole_file(tmp_path) -> None:
    target = tmp_path / "artifact.bin"
    staging = tmp_path / ".artifact.bin.transfer.tmp"
    staging.write_bytes(b"abc")
    raw = b"abcdef"
    writer = VerifiedStagingWriter(
        target,
        expected_size=len(raw),
        expected_sha256=hashlib.sha256(raw).hexdigest(),
        resume_offset=3,
    )

    writer.write(b"def")
    writer.finish()

    assert target.read_bytes() == raw
    assert verify_file(
        target,
        expected_size=6,
        expected_sha256=hashlib.sha256(raw).hexdigest(),
    )


def test_cancel_removes_only_staging_file(tmp_path) -> None:
    target = tmp_path / "artifact.bin"
    target.write_bytes(b"retained")
    writer = VerifiedStagingWriter(
        target,
        expected_size=3,
        expected_sha256=hashlib.sha256(b"abc").hexdigest(),
    )
    writer.write(b"new")
    writer.cancel()

    assert target.read_bytes() == b"retained"
    assert not writer.staging_path.exists()
