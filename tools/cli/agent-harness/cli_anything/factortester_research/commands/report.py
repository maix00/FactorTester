"""Expose the production Work Package report commands to the harness.

The harness is an agent-facing skin, not a second report implementation.  It
therefore shares the exact Profile / Work Package / branch scoped command
surface used by ``factortester research reports``.
"""

from tools.cli.commands.research_report import report

__all__ = ["report"]
