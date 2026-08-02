"""Cold-path indexes required by profile research projections."""

from __future__ import annotations

import sqlite3


def ensure_profile_research_indexes(conn: sqlite3.Connection) -> None:
    """Create query-only indexes during the existing cold schema path."""
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_research_graph_instances_owner_workspace
        ON research_graph_instances(owner, workspace_id, instance_id)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_research_graph_instances_owner_mode
        ON research_graph_instances(owner, mode, instance_id)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_research_graph_branches_instance_updated
        ON research_graph_branches(
            instance_id, updated_at DESC, branch_id DESC
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_research_graph_trace_branch_timeline
        ON research_graph_trace(
            instance_id, branch_id, created_at DESC, trace_id DESC
        )
        """
    )
