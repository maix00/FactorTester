"""The released client exposes independent research and report commands."""

from __future__ import annotations

import shutil
import subprocess

from tools.cli.release.materialize import materialize_release

from .test_client_wheel import _build_wheel


def test_client_wheel_materializes_research_cli_without_graph_harness(tmp_path):
    staging = tmp_path / "release"
    artifacts = staging / "artifacts"
    artifacts.mkdir(parents=True)
    wheel = _build_wheel(tmp_path / "client-build")
    shutil.copy2(wheel, artifacts / wheel.name)
    result = materialize_release(
        staging, [{"filename": wheel.name, "kind": "python-wheel"}],
    )

    assert result["python"]["commands"] == [
        "factortester", "factortester-manager",
    ]
    binary = staging / "runtime" / "python" / "bin" / "factortester"
    output = subprocess.check_output(
        [binary, "research", "reports", "--help"], text=True,
    )
    assert "branch-fork" in output
    assert "copy-preview" in output
    assert "graph" not in output.lower()
