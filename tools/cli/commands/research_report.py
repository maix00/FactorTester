"""Report Workspace-scoped research report commands."""

from __future__ import annotations

import click

from .research_report_authoring import register_authoring_commands
from .research_report_branch import register_branch_commands
from .research_report_copy import copy_preview
from .research_report_copy_apply import copy_apply
from .research_report_export import export_report
from .research_report_inspection import register_inspection_commands
from .research_report_publication import publication


@click.group("report")
def report() -> None:
    """Author one branch report inside its Report Workspace; no loose files.

    Rich text uses portable Markdown.  Reference domain objects inline with a
    typed link such as ``[IC 证据](factortester://evidence/evidence%3Aic-2025)``.
    Evidence, Jobs, Runs, and TrialPlans remain owned by their own modules;
    report commands only link to those independently validated objects.
    """


register_authoring_commands(report)
register_branch_commands(report)
register_inspection_commands(report)
report.add_command(copy_preview)
report.add_command(copy_apply)
report.add_command(export_report)
report.add_command(publication)
