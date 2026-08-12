"""One-row historical checkpoint Carrier lookup across graph incarnations."""

REPORT_CHECKPOINT_SQL = """
    SELECT t.trace_id, t.instance_id AS trace_instance_id,
           t.branch_id AS trace_branch_id, t.edge_id, t.from_node, t.to_node,
           t.created_at AS trace_created_at, t.evidence_json,
           history.label,
           history_instance.graph_id, history_instance.graph_version,
           history_instance.product_group, history_instance.workspace_id,
           COALESCE(
               NULLIF(history_instance.work_package_id, ''),
               history_instance.instance_id
           ) AS work_package_id
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
      ON t.instance_id=history.instance_id
     AND t.branch_id=history.branch_id
     AND t.trace_id=?
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
    LIMIT 1
"""
