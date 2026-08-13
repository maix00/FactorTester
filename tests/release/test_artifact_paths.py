from __future__ import annotations

from pathlib import Path

from tools.cli.release.artifact_paths import artifact_destination


def test_output_artifact_uses_only_safe_file_name(tmp_path: Path) -> None:
    target = artifact_destination(tmp_path, {
        "name": "table",
        "file_name": "metrics.csv",
        "role": "output",
    })

    assert target == tmp_path / "metrics.csv"


def test_input_artifact_preserves_safe_logical_path(tmp_path: Path) -> None:
    target = artifact_destination(tmp_path, {
        "name": "run_dependency__1",
        "file_name": "settings.yaml",
        "role": "input",
        "artifact_kind": "run_dependency",
        "logical_path": "strategies/alpha/settings.yaml",
    })

    assert target == (
        tmp_path / "inputs" / "run_dependency"
        / "strategies" / "alpha" / "settings.yaml"
    )


def test_unsafe_input_path_falls_back_to_file_name(tmp_path: Path) -> None:
    target = artifact_destination(tmp_path, {
        "name": "source",
        "file_name": "factor.py",
        "role": "input",
        "artifact_kind": "factor source",
        "logical_path": "../../outside.py",
    })

    assert target == tmp_path / "inputs" / "factor-source" / "factor.py"
