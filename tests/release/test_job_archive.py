from __future__ import annotations

import io
from pathlib import Path
import zipfile

import pytest

from tools.cli.release.job_archive import extract_job_archive


def _archive(items: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as bundle:
        for name, raw in items.items():
            bundle.writestr(name, raw)
    return output.getvalue()


def test_extract_job_archive_leaves_only_usable_files(tmp_path: Path) -> None:
    files = extract_job_archive(
        _archive({"fee.csv": b"metric,value\nsharpe,1.2\n"}), tmp_path / "job-1",
    )
    assert [path.name for path in files] == ["fee.csv"]
    assert files[0].read_bytes().startswith(b"metric")
    assert not list((tmp_path / "job-1").glob("*.zip"))


def test_extract_job_archive_rejects_escaped_members(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="越界"):
        extract_job_archive(_archive({"../outside.txt": b"no"}), tmp_path / "job-1")
    assert not (tmp_path / "outside.txt").exists()
