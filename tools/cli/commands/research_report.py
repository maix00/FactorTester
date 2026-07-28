"""Work Package-scoped research report commands."""

from __future__ import annotations

import json

import click

from tools.cli.release.research_reporting.authoring.chips import (
    chip_descriptor,
    chip_kinds,
)

from .research_report_authoring import register_authoring_commands
from .research_report_inspection import register_inspection_commands


@click.group("report")
def report() -> None:
    """Author one branch report inside its Work Package; no loose files."""


@report.command("chip-kinds")
@click.option("--locale", default="zh-Hans", show_default=True)
@click.option("--json", "as_json", is_flag=True)
def list_chip_kinds(locale: str, as_json: bool) -> None:
    descriptors = [
        chip_descriptor({"kind": kind, "chip_id": "", "target_ref": ""}, locale=locale)
        for kind in chip_kinds()
    ]
    if as_json:
        click.echo(json.dumps(
            {"locale": locale, "chips": descriptors}, ensure_ascii=False,
            indent=2, sort_keys=True,
        ))
        return
    for item in descriptors:
        click.echo(f"{item['kind']}: {item['display_label']} -> {item['target']}")


register_authoring_commands(report)
register_inspection_commands(report)
