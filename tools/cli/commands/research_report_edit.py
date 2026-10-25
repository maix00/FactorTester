"""CLI commands for CouchDB-authoritative Research Report edits."""

from __future__ import annotations

import json
from typing import Any

import click

from tools.cli.core.context import client_from_config
from tools.cli.core.errors import friendly_errors


def register_research_report_edit_commands(research: click.Group) -> None:
    @research.command("report-document")
    @click.argument("publication_id")
    @click.option("--json", "as_json", is_flag=True)
    @friendly_errors
    def report_document(publication_id: str, as_json: bool) -> None:
        """Read one CouchDB Research Report document."""
        client, _ = client_from_config()
        value = client.research_report(publication_id)
        click.echo(json.dumps(value, ensure_ascii=False, indent=2) if as_json else
                   f"{value.get('publication_id')} {value.get('title')} rev={value.get('_rev')}")

    @research.command("report-operation")
    @click.argument("publication_id")
    @click.option("--base-rev", required=True)
    @click.option("--json", "payload", required=True, help="Operation JSON object.")
    @friendly_errors
    def report_operation(publication_id: str, base_rev: str, payload: str) -> None:
        """Apply one revision-checked insert/move/remove/batch operation."""
        operation: dict[str, Any] = json.loads(payload)
        client, _ = client_from_config()
        value = client.apply_research_report_operation(
            publication_id, base_rev=base_rev, operation=operation,
        )
        click.echo(json.dumps(value, ensure_ascii=False, indent=2))


__all__ = ["register_research_report_edit_commands"]
