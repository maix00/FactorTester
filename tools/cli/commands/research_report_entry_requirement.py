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


def validate_report_requirement_section(
    *,
    kind: str,
    display_kind: str,
    obligation_requirement_id: str,
    report_requirement_id: str,
    report_subject_ref: str,
) -> None:
    """Keep requirement reports inside their explicitly bound special."""
    report_id = report_requirement_id.strip()
    if not report_id.startswith("report.requirement."):
        return
    requirement_id = report_id.removeprefix("report.requirement.")
    selected = obligation_requirement_id.strip()
    if (
        kind != "special"
        or display_kind != "obligation_requirement"
        or not selected
    ):
        raise click.ClickException(
            f"{report_id} must use --kind special --display-kind "
            "obligation_requirement --obligation-requirement-id "
            f"{requirement_id}"
        )
    subject = report_subject_ref.strip()
    if subject.startswith("requirement:"):
        subject_requirement = subject.removeprefix("requirement:")
        if selected != subject_requirement:
            raise click.ClickException(
                "--obligation-requirement-id must match the report "
                "requirement subject"
            )
    elif selected != requirement_id:
        raise click.ClickException(
            "--obligation-requirement-id must match the Graph report "
            "requirement"
        )
