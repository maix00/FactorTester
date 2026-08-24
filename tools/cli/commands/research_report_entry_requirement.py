"""Bind an authored special section to one obligation requirement category."""

from __future__ import annotations

import re
from typing import Any

import click

from tools.cli.core.context import client_from_config
from tools.cli.release.research_obligations import ledger_path, load_ledger
from tools.cli.release.research_reporting.authoring.declared_links import (
    DeclaredReportReference,
)
from tools.cli.release.research_reporting.authoring.inline_links import (
    typed_link_list,
)
from tools.cli.release.research_reporting.references.entry_requirements import (
    validate_entry_requirement_reference,
)

_LIST_ITEM = re.compile(r"^(?:[-+*]|\d+[.)])\s+")


def obligation_requirement_body(
    *,
    body: str,
    kind: str,
    display_kind: str,
    requirement_id: str,
    title_zh: str,
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
    title = title_zh.strip()
    if not title:
        raise click.ClickException(
            "obligation requirement has no authoritative title_zh"
        )
    link = typed_link_list([{
        "kind": "entry_requirement",
        "target_ref": f"requirement:{selected}",
        "label": title,
    }])
    return normalize_obligation_requirement_body(body=body, link=link)


def normalize_obligation_requirement_body(*, body: str, link: str) -> str:
    """Keep the typed category as the first item without a wrapper heading."""
    content = body.strip()
    target_url = link.rsplit("](", 1)[-1].removesuffix(")")
    legacy = re.compile(
        rf"(?:\n\n|^)?关联[：:]\s*\n-\s+"
        rf"\[(?:\\.|[^\]\n])+\]\({re.escape(target_url)}\)\s*$"
    )
    content = legacy.sub("", content).strip()
    if content == link:
        return link
    if content.startswith(link + "\n"):
        content = content[len(link):].lstrip("\n")
    if not content:
        return link
    separator = "\n" if _LIST_ITEM.match(content) else "\n\n"
    return f"{link}{separator}{content}"


def resolve_obligation_requirement_title(
    *, scope: Any, requirement_id: str, allow_historical: bool,
) -> str:
    """Resolve the immutable Graph title before generating report prose."""
    selected = requirement_id.strip()
    if not selected:
        return ""
    local_title = _frozen_requirement_title(scope, selected)
    if local_title:
        return local_title
    client = client_from_config()
    try:
        metadata = validate_entry_requirement_reference(
            reference=DeclaredReportReference(
                kind="entry_requirement",
                target_ref=f"requirement:{selected}",
                label=selected,
            ),
            scope=scope,
            client=client,
            allow_historical=allow_historical,
        )
    except (KeyError, LookupError, OSError, RuntimeError, ValueError) as error:
        raise click.ClickException(str(error)) from error
    title = str(metadata.get("title_zh") or "").strip()
    if not title:
        raise click.ClickException(
            f"requirement catalog has no title_zh: {selected}"
        )
    return title


def _frozen_requirement_title(scope: Any, requirement_id: str) -> str:
    """Prefer the short title already frozen once in the branch ledger."""
    path = ledger_path(scope.package_root, scope.branch_id)
    if not path.exists():
        return ""
    ledger = load_ledger(scope.package_root, scope.branch_id)
    for event in reversed(ledger.get("history") or []):
        titles = event.get("requirement_titles") or {}
        title = str(titles.get(requirement_id) or "").strip()
        if title:
            return title
    return ""


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
