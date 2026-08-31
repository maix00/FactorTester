"""The released client has no fallback path for retired report formats."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from tools.cli.app import cli


def test_client_research_exposes_no_legacy_report_migration_command() -> None:
    result = CliRunner().invoke(cli, ["research", "--help"])

    assert result.exit_code == 0, result.output
    assert "migrate-work-packages" not in result.output


def test_authoring_package_contains_only_report_tree_runtime_modules() -> None:
    from tools.cli.release.research_reporting import authoring

    root = authoring.__path__[0]
    retired = {
        "legacy_document.py", "legacy_import.py", "legacy_inventory.py",
        "legacy_journal.py", "legacy_journal_links.py", "legacy_projections.py",
        "legacy_sources.py", "migration.py", "migration_record.py",
        "migration_steps.py",
    }
    names = {item.name for item in Path(root).iterdir()}
    assert not retired & names
