"""Bounded timeline queries for current and continued branches."""

TIMELINE_FIRST_SQL = """
    SELECT t.trace_id, t.instance_id AS trace_instance_id,
           t.branch_id AS trace_branch_id, t.rowid AS trace_rowid,
           t.edge_id, t.from_node, t.to_node, t.actor,
           t.acting_profile_ref,
           t.created_at, t.evidence_json, b.status AS branch_status,
           b.latest_trace_id
    FROM research_graph_instances AS i
    JOIN research_graph_branches AS b
      ON b.instance_id=i.instance_id AND b.branch_id=?
    LEFT JOIN research_graph_trace AS t
      ON t.instance_id=i.instance_id AND t.branch_id=b.branch_id
    WHERE i.owner=? AND i.instance_id=?
    ORDER BY t.created_at DESC, t.trace_id DESC
    LIMIT ?
"""

TIMELINE_AFTER_SQL = """
    SELECT t.trace_id, t.instance_id AS trace_instance_id,
           t.branch_id AS trace_branch_id, t.rowid AS trace_rowid,
           t.edge_id, t.from_node, t.to_node, t.actor,
           t.acting_profile_ref, t.created_at, t.evidence_json,
           b.status AS branch_status,
           b.latest_trace_id
    FROM research_graph_instances AS i
    JOIN research_graph_branches AS b
      ON b.instance_id=i.instance_id AND b.branch_id=?
    LEFT JOIN research_graph_trace AS t
      ON t.instance_id=i.instance_id AND t.branch_id=b.branch_id
      AND (
        t.created_at<?
        OR (t.created_at=? AND t.trace_id<?)
      )
    WHERE i.owner=? AND i.instance_id=?
    ORDER BY t.created_at DESC, t.trace_id DESC
    LIMIT ?
"""

WORK_PACKAGE_TIMELINE_FIRST_SQL = """
    SELECT t.trace_id, t.instance_id AS trace_instance_id,
           t.branch_id AS trace_branch_id,
           t.rowid AS trace_rowid,
           t.edge_id, t.from_node, t.to_node, t.actor,
           t.acting_profile_ref, t.created_at, t.evidence_json,
           current.status AS branch_status,
           current.latest_trace_id,
           current.instance_id AS current_instance_id
    FROM research_graph_instances AS current_instance
    JOIN research_graph_branches AS current
      ON current.instance_id=current_instance.instance_id
     AND current.branch_id=? AND current.is_current_incarnation=1
    JOIN research_graph_branches AS history
      ON COALESCE(NULLIF(history.hypothesis_branch_id, ''), history.branch_id)
       = COALESCE(NULLIF(current.hypothesis_branch_id, ''), current.branch_id)
    JOIN research_graph_instances AS history_instance
      ON history_instance.instance_id=history.instance_id
    LEFT JOIN research_graph_trace AS t
      ON t.instance_id=history.instance_id AND t.branch_id=history.branch_id
    WHERE current_instance.owner=?
      AND COALESCE(
          NULLIF(current_instance.work_package_id, ''),
          current_instance.instance_id
      )=?
      AND history_instance.owner=current_instance.owner
      AND COALESCE(
          NULLIF(history_instance.work_package_id, ''),
          history_instance.instance_id
      )=COALESCE(
          NULLIF(current_instance.work_package_id, ''),
          current_instance.instance_id
      )
    ORDER BY t.created_at DESC, t.trace_id DESC
    LIMIT ?
"""

WORK_PACKAGE_TIMELINE_AFTER_SQL = WORK_PACKAGE_TIMELINE_FIRST_SQL.replace(
    "WHERE current_instance.owner=?",
    """WHERE t.trace_id IS NOT NULL AND (
        t.created_at<? OR (t.created_at=? AND t.trace_id<?)
    ) AND current_instance.owner=?""",
)

_DETOUR_BOUNDARY = """
    (
      t.edge_id='__graph_continuation__'
      OR t.from_node IN (
        'capability_gap', 'capability_resolution',
        'skill_candidate_review', 'code_improvement_required'
      )
      OR t.to_node IN (
        'capability_gap', 'capability_resolution',
        'skill_candidate_review', 'code_improvement_required'
      )
    )
"""

_DETOUR_REPLAY_EVIDENCE = """
    CASE
      WHEN t.edge_id='__graph_continuation__' THEN t.evidence_json
      WHEN json_type(
        t.evidence_json, '$.capability_detour_delta'
      )='object' THEN json_object(
        'capability_detour_delta',
        json_extract(t.evidence_json, '$.capability_detour_delta')
      )
      ELSE '{}'
    END
"""

TIMELINE_PLACEMENT_SQL = f"""
    SELECT t.trace_id, t.edge_id, t.from_node, t.to_node,
           t.created_at, t.rowid AS trace_rowid,
           {_DETOUR_REPLAY_EVIDENCE} AS evidence_json
    FROM research_graph_instances AS i
    JOIN research_graph_branches AS b
      ON b.instance_id=i.instance_id AND b.branch_id=?
    JOIN research_graph_trace AS t
      ON t.instance_id=i.instance_id AND t.branch_id=b.branch_id
    WHERE i.owner=? AND i.instance_id=? AND {_DETOUR_BOUNDARY}
    ORDER BY t.created_at ASC, t.rowid ASC
"""

WORK_PACKAGE_TIMELINE_PLACEMENT_SQL = f"""
    SELECT t.trace_id, t.edge_id, t.from_node, t.to_node,
           t.created_at, t.rowid AS trace_rowid,
           {_DETOUR_REPLAY_EVIDENCE} AS evidence_json
    FROM research_graph_instances AS current_instance
    JOIN research_graph_branches AS current
      ON current.instance_id=current_instance.instance_id
     AND current.branch_id=? AND current.is_current_incarnation=1
    JOIN research_graph_branches AS history
      ON COALESCE(NULLIF(history.hypothesis_branch_id, ''), history.branch_id)
       = COALESCE(NULLIF(current.hypothesis_branch_id, ''), current.branch_id)
    JOIN research_graph_instances AS history_instance
      ON history_instance.instance_id=history.instance_id
    JOIN research_graph_trace AS t
      ON t.instance_id=history.instance_id AND t.branch_id=history.branch_id
    WHERE current_instance.owner=?
      AND COALESCE(
          NULLIF(current_instance.work_package_id, ''),
          current_instance.instance_id
      )=?
      AND history_instance.owner=current_instance.owner
      AND COALESCE(
          NULLIF(history_instance.work_package_id, ''),
          history_instance.instance_id
      )=COALESCE(
          NULLIF(current_instance.work_package_id, ''),
          current_instance.instance_id
      )
      AND {_DETOUR_BOUNDARY}
    ORDER BY t.created_at ASC, t.rowid ASC
"""
