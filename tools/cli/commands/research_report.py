"""Work Package-scoped research report commands."""

from __future__ import annotations

import click

from .research_report_authoring import register_authoring_commands
from .research_report_branch import register_branch_commands
from .research_report_export import export_report
from .research_report_inspection import register_inspection_commands
from .research_report_publication import publication


@click.group("report")
def report() -> None:
    """Author one branch report inside its Work Package; no loose files.

    Rich text uses portable Markdown.  Reference domain objects inline with a
    typed link such as ``[IC 证据](factortester://evidence/evidence%3Aic-2025)``.
    Evidence, obligations, Jobs, and Tasks remain owned by their own modules;
    report commands never register them.  System-generated report requirement
    bindings remain machine-readable metadata; reader-facing obligation
    requirement specials carry the corresponding typed requirement links.
    """


register_authoring_commands(report)
register_branch_commands(report)
register_inspection_commands(report)
report.add_command(export_report)
report.add_command(publication)
