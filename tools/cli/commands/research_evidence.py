"""Native CLI surface for persistent reusable research Evidence."""

from __future__ import annotations

import click

from .research_evidence_query import register_query_commands
from .research_evidence_sources import register_source_commands
from .research_evidence_tags import register_tag_commands


@click.group("evidence")
def research_evidence() -> None:
    """Capture fragments, create Evidence, search facets and manage tags."""


register_query_commands(research_evidence)
register_source_commands(research_evidence)
register_tag_commands(research_evidence)
