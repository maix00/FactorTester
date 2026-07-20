from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

from tools.cli.release.materialize import materialize_release

from .test_client_wheel import _build_wheel as build_client_wheel
from .test_harness_wheel import _build_wheel as build_harness_wheel


def test_real_client_and_harness_wheels_materialize_together(
    tmp_path: Path,
) -> None:
    staging = tmp_path / "release"
    artifacts = staging / "artifacts"
    client = build_client_wheel(tmp_path / "client-build")
    harness = build_harness_wheel(tmp_path / "harness-build")
    artifacts.mkdir(parents=True)
    installed = [
        (client, "python-wheel"),
        (harness, "harness-wheel"),
    ]
    receipts = []
    for source, kind in installed:
        shutil.copy2(source, artifacts / source.name)
        receipts.append({"filename": source.name, "kind": kind})

    result = materialize_release(staging, receipts)

    assert result["python"]["commands"] == [
        "factortester",
        "cli-anything-factortester-research",
    ]
    bin_root = staging / "runtime" / "python" / "bin"
    client_help = subprocess.check_output(
        [bin_root / "factortester", "--help"],
        text=True,
    )
    harness_help = subprocess.check_output(
        [bin_root / "cli-anything-factortester-research", "--help"],
        text=True,
    )
    assert "protocol" in client_help
    assert "cycle" in harness_help
