"""Bind an authored special section to one obligation requirement category."""

from __future__ import annotations

import click

from tools.cli.release.research_reporting.authoring.inline_links import (
    typed_link_list,
)


def obligation_requirement_body(
    *,
    body: str,
    kind: str,
    display_kind: str,
    requirement_id: str,
) -> str:
    selected = requirement_id.strip()
    tagged = display_kind == "obligation_requirement"
    if not selected and not tagged:
        return body
    if not selected:
        raise click.ClickException(
            "--display-kind obligation_requirement requires "
            "--obligation-requirement-id"
        )
    if kind != "special" or not tagged:
        raise click.ClickException(
            "--obligation-requirement-id requires --kind special and "
            "--display-kind obligation_requirement"
        )
    link = typed_link_list([{
        "kind": "entry_requirement",
        "target_ref": f"requirement:{selected}",
        "label": "义务小类",
    }])
    return f"{body}\n\n关联：\n{link}".strip()
