"""Behavior contract for report leaf lazy rendering."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_report_leaf_rendering_waits_for_intersection() -> None:
    fixture = ROOT / "tests" / "scripts" / "fixtures" / "report_lazy_renderer.js"
    result = subprocess.run(
        ["node", str(fixture)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_large_report_tables_render_in_idle_chunks() -> None:
    fixture = ROOT / "tests" / "scripts" / "fixtures" / "report_table_rendering.js"
    result = subprocess.run(
        ["node", str(fixture)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_report_chapter_cache_is_bounded_lru() -> None:
    fixture = ROOT / "tests" / "scripts" / "fixtures" / "report_chapter_cache.js"
    result = subprocess.run(
        ["node", str(fixture)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_report_tree_index_is_data_only() -> None:
    fixture = ROOT / "tests" / "scripts" / "fixtures" / "report_tree.js"
    result = subprocess.run(
        ["node", str(fixture)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_report_chapter_cache_is_bounded_data_only() -> None:
    fixture = ROOT / "tests" / "scripts" / "fixtures" / "report_chapter_cache_unit.js"
    result = subprocess.run(
        ["node", str(fixture)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_report_source_keeps_local_and_shared_loading_in_one_seam() -> None:
    fixture = ROOT / "tests" / "scripts" / "fixtures" / "report_source.js"
    result = subprocess.run(
        ["node", str(fixture)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_web_rich_text_preserves_nested_factor_label_brackets() -> None:
    fixture = ROOT / "tests" / "scripts" / "fixtures" / "report_rich_text_links.js"
    result = subprocess.run(
        ["node", str(fixture)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_report_job_links_keep_the_federated_server_route() -> None:
    fixture = ROOT / "tests" / "scripts" / "fixtures" / "report_job_navigation.js"
    result = subprocess.run(
        ["node", str(fixture)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"
