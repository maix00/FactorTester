"""Behavior contract for Swift-owned Web reference tabs."""

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_reference_page_maps_stable_object_endpoints() -> None:
    fixture = ROOT / "tests" / "scripts" / "fixtures" / "reference_page.js"
    result = subprocess.run(
        ["node", str(fixture)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_run_spec_view_separates_identity_configuration_and_execution() -> None:
    fixture = ROOT / "tests" / "scripts" / "fixtures" / "run_spec_view.js"
    result = subprocess.run(
        ["node", str(fixture)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_jobs_module_keeps_detail_table_seam() -> None:
    source = (ROOT / "server" / "manager" / "web" / "jobs" / "jobs.js").read_text(
        encoding="utf-8",
    )
    # Formatting now lives in the shared list/detail seam; the controller
    # consumes its table helper through the destructured interface.
    assert "    scalar, serverLabel, statusCell, statusPill, table, taskCell, taskHash, taskTitle, text," in source
    assert "window.FTJobs =" in source
