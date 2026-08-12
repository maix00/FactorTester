"""Build the optional research-graph requirement annotation."""

from __future__ import annotations

import hashlib

import click


def report_requirement(
    *, component_id: str, body: str, requirement_id: str, subject_ref: str,
    content_kind: str,
) -> tuple[dict[str, object] | None, str]:
    fields = (requirement_id, subject_ref, content_kind)
    if not any(fields):
        return None, body
    if not all(fields):
        raise click.ClickException(
            "--report-requirement-id, --report-subject-ref and "
            "--report-content-kind must be used together"
        )
    identifier = hashlib.sha256(
        "\x1f".join((component_id, requirement_id, subject_ref)).encode()
    ).hexdigest()[:48]
    binding = {
        "binding_id": f"report-requirement-{identifier}",
        "kind": "report_requirement", "target_ref": requirement_id,
        "label": "报告义务",
        "data": {
            "report_requirement_id": requirement_id,
            "subject_ref": subject_ref, "content_kind": content_kind,
        },
    }
    # A report requirement is a machine-readable coverage contract.  It must
    # remain attached to the component for Graph gates and report hashes, but
    # it is not a reader-facing domain reference.  Visible requirement links
    # belong to obligation-requirement specials and use entry_requirement.
    return binding, body
