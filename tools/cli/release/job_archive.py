"""Safe extraction of remote Job artifact bundles."""

from __future__ import annotations

import io
from pathlib import Path
import zipfile


def extract_job_archive(raw: bytes, destination: Path) -> list[Path]:
    """Extract an archive without retaining a ZIP or permitting Zip Slip."""
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    extracted: list[Path] = []
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            target = (root / info.filename).resolve()
            if root not in target.parents or target == root:
                raise ValueError("Job 生成物压缩包包含越界路径")
            target.parent.mkdir(parents=True, exist_ok=True)
            staging = target.with_name(f".{target.name}.part")
            with archive.open(info) as source, staging.open("wb") as output:
                while chunk := source.read(64 * 1024):
                    output.write(chunk)
            staging.replace(target)
            extracted.append(target)
    return extracted
