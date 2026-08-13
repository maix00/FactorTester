"""Streaming SHA-256 verification and atomic destination promotion."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path


class IntegrityError(RuntimeError):
    pass


def verify_file(
    path: str | Path,
    *,
    expected_size: int,
    expected_sha256: str,
) -> bool:
    target = Path(path)
    digest = hashlib.sha256()
    size = 0
    with target.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    if size != int(expected_size):
        raise IntegrityError(
            f"file size mismatch: expected {expected_size}, received {size}"
        )
    expected = str(expected_sha256 or "").strip().lower()
    if expected and digest.hexdigest() != expected:
        raise IntegrityError("file SHA-256 mismatch")
    return True


class VerifiedStagingWriter:
    def __init__(
        self,
        target: str | Path,
        *,
        expected_size: int,
        expected_sha256: str,
        resume_offset: int = 0,
    ) -> None:
        self.target = Path(target).expanduser().resolve()
        self.target.parent.mkdir(parents=True, exist_ok=True)
        self.staging_path = self.target.with_name(
            f".{self.target.name}.transfer.tmp"
        )
        self.expected_size = int(expected_size)
        self.expected_sha256 = str(expected_sha256 or "").strip().lower()
        self.resume_offset = int(resume_offset)
        if self.expected_size < 0 or not 0 <= self.resume_offset <= self.expected_size:
            raise ValueError("staging size or resume offset is invalid")
        if self.resume_offset:
            if (
                not self.staging_path.is_file()
                or self.staging_path.stat().st_size != self.resume_offset
            ):
                raise IntegrityError("staging prefix does not match resume offset")
            self._stream = self.staging_path.open("ab")
            self.bytes_written = self.resume_offset
        else:
            self._stream = self.staging_path.open("wb")
            self.staging_path.chmod(0o600)
            self.bytes_written = 0
        self._closed = False

    def write(self, value: bytes) -> None:
        if self._closed:
            raise RuntimeError("staging writer is closed")
        raw = bytes(value)
        if self.bytes_written + len(raw) > self.expected_size:
            self.cancel()
            raise IntegrityError("received bytes exceed expected size")
        self._stream.write(raw)
        self.bytes_written += len(raw)

    def finish(self) -> Path:
        if self._closed:
            raise RuntimeError("staging writer is closed")
        self._stream.flush()
        os.fsync(self._stream.fileno())
        self._stream.close()
        self._closed = True
        try:
            verify_file(
                self.staging_path,
                expected_size=self.expected_size,
                expected_sha256=self.expected_sha256,
            )
        except BaseException:
            self.staging_path.unlink(missing_ok=True)
            raise
        os.replace(self.staging_path, self.target)
        return self.target

    def cancel(self) -> None:
        if not self._closed:
            self._stream.close()
            self._closed = True
        self.staging_path.unlink(missing_ok=True)

    def preserve(self) -> Path:
        """Close a partial stream without making it visible as a final file."""

        if not self._closed:
            self._stream.flush()
            os.fsync(self._stream.fileno())
            self._stream.close()
            self._closed = True
        return self.staging_path
