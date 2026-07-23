"""Bounded Work Package and Hypothesis Branch detail queries."""

TREE_FIRST_WINDOW = 1
TREE_LAST_WINDOW = 1
MAX_TREE_NODES = 120

WORK_PACKAGE_DETAIL_SQL = f"""
    SELECT i.instance_id,
           COALESCE(NULLIF(i.work_package_id, ''), i.instance_id)
               AS work_package_id,
           i.created_by_profile_ref,
           i.current_owner_profile_ref, i.graph_id, i.graph_version,
           COALESCE(wp.lifecycle, 'active') AS lifecycle,
           COALESCE(wp.revision, 1) AS lifecycle_revision,
           i.product_group,
           i.workspace_id, i.mode,
           (
               SELECT MIN(root.created_at)
               FROM research_graph_instances AS root
               WHERE root.owner=i.owner AND COALESCE(
                   NULLIF(root.work_package_id, ''), root.instance_id
               )=COALESCE(NULLIF(i.work_package_id, ''), i.instance_id)
           ) AS instance_created_at,
           b.branch_id, b.hypothesis_branch_id,
           b.label, b.current_node, b.status,
           b.current_trial_plan_hash, b.latest_trace_id,
           b.created_at, b.updated_at,
           lineage.edge_id AS lineage_edge_id,
           lineage.evidence_json AS lineage_evidence_json,
           CASE WHEN b.branch_id=(
               SELECT candidate.branch_id
               FROM research_graph_branches AS candidate
               JOIN research_graph_instances AS candidate_instance
                 ON candidate_instance.instance_id=candidate.instance_id
               WHERE COALESCE(
                   NULLIF(candidate_instance.work_package_id, ''),
                   candidate_instance.instance_id
               )=COALESCE(NULLIF(i.work_package_id, ''), i.instance_id)
               ORDER BY candidate.updated_at DESC,
                        candidate_instance.graph_version DESC,
                        candidate.branch_id DESC
               LIMIT 1
           ) THEN (
               SELECT json_object(
                   'nodes', COALESCE(json_group_array(json_object(
                       'trace_id', selected.trace_id,
                       'instance_id', selected.instance_id,
                       'graph_id', selected.graph_id,
                       'graph_version', selected.graph_version,
                       'branch_id', selected.branch_id,
                       'hypothesis_branch_id', selected.hypothesis_branch_id,
                       'edge_id', selected.edge_id,
                       'from_node', selected.from_node,
                       'to_node', selected.to_node,
                       'created_at', selected.created_at,
                       'branch_status', selected.branch_status,
                       'latest_trace_id', selected.latest_trace_id,
                       'first_rank', selected.first_rank,
                       'last_rank', selected.last_rank
                   )), json('[]')),
                   'omitted_node_count', MAX(selected.total_trace_count)
                       - COUNT(selected.trace_id)
               )
               FROM (
                   SELECT ranked.*
                   FROM (
                       SELECT t.trace_id, t.instance_id,
                              trace_instance.graph_id,
                              trace_instance.graph_version,
                              t.branch_id,
                              COALESCE(
                                  NULLIF(branch.hypothesis_branch_id, ''),
                                  branch.branch_id
                              ) AS hypothesis_branch_id,
                              t.edge_id,
                              t.from_node, t.to_node, t.created_at,
                              COALESCE((
                                  SELECT current.status
                                  FROM research_graph_branches AS current
                                  WHERE COALESCE(
                                      NULLIF(current.hypothesis_branch_id, ''),
                                      current.branch_id
                                  )=COALESCE(
                                      NULLIF(branch.hypothesis_branch_id, ''),
                                      branch.branch_id
                                  ) AND current.is_current_incarnation=1
                                  LIMIT 1
                              ), branch.status) AS branch_status,
                              COALESCE((
                                  SELECT current.latest_trace_id
                                  FROM research_graph_branches AS current
                                  WHERE COALESCE(
                                      NULLIF(current.hypothesis_branch_id, ''),
                                      current.branch_id
                                  )=COALESCE(
                                      NULLIF(branch.hypothesis_branch_id, ''),
                                      branch.branch_id
                                  ) AND current.is_current_incarnation=1
                                  LIMIT 1
                              ), branch.latest_trace_id) AS latest_trace_id,
                              branch.latest_trace_id AS incarnation_latest_trace_id,
                              ROW_NUMBER() OVER (
                                  PARTITION BY COALESCE(
                                      NULLIF(branch.hypothesis_branch_id, ''),
                                      branch.branch_id
                                  )
                                  ORDER BY t.created_at ASC, t.trace_id ASC
                              ) AS first_rank,
                              ROW_NUMBER() OVER (
                                  PARTITION BY COALESCE(
                                      NULLIF(branch.hypothesis_branch_id, ''),
                                      branch.branch_id
                                  )
                                  ORDER BY t.created_at DESC, t.trace_id DESC
                              ) AS last_rank,
                              COUNT(*) OVER () AS total_trace_count
                       FROM research_graph_trace AS t
                       JOIN research_graph_branches AS branch
                         ON branch.instance_id=t.instance_id
                        AND branch.branch_id=t.branch_id
                       JOIN research_graph_instances AS trace_instance
                         ON trace_instance.instance_id=t.instance_id
                       WHERE COALESCE(
                           NULLIF(trace_instance.work_package_id, ''),
                           trace_instance.instance_id
                       )=COALESCE(
                           NULLIF(i.work_package_id, ''), i.instance_id
                       )
                         AND t.branch_id IN (
                             SELECT visible.branch_id
                             FROM research_graph_branches AS visible
                             JOIN research_graph_instances AS visible_instance
                               ON visible_instance.instance_id=visible.instance_id
                             WHERE COALESCE(
                                 NULLIF(visible_instance.work_package_id, ''),
                                 visible_instance.instance_id
                             )=COALESCE(
                                 NULLIF(i.work_package_id, ''), i.instance_id
                             )
                             ORDER BY visible.updated_at DESC,
                                      visible.branch_id DESC
                             LIMIT 50
                         )
                   ) AS ranked
                   WHERE ranked.total_trace_count<={MAX_TREE_NODES}
                      OR ranked.first_rank<={TREE_FIRST_WINDOW}
                      OR ranked.last_rank<={TREE_LAST_WINDOW}
                      OR ranked.trace_id=ranked.incarnation_latest_trace_id
                      OR ranked.edge_id IN (
                          '__branch_fork__', '__graph_continuation__'
                      )
                   ORDER BY ranked.created_at ASC, ranked.trace_id ASC
                   LIMIT {MAX_TREE_NODES}
               ) AS selected
           ) ELSE NULL END AS tree_json,
           COUNT(*) OVER () AS total_branch_count
    FROM research_graph_instances AS i
    JOIN research_graph_branches AS b
      ON b.instance_id=i.instance_id
    LEFT JOIN research_work_packages AS wp
      ON wp.owner=i.owner
     AND wp.work_package_id=COALESCE(
         NULLIF(i.work_package_id, ''), i.instance_id
     )
    LEFT JOIN research_graph_trace AS lineage
      ON lineage.trace_id=(
          SELECT candidate.trace_id
          FROM research_graph_trace AS candidate
          WHERE candidate.instance_id=b.instance_id
            AND candidate.branch_id=b.branch_id
            AND candidate.created_at=b.created_at
            AND candidate.edge_id IN (
                '__branch_fork__', '__graph_continuation__'
            )
          ORDER BY candidate.trace_id
          LIMIT 1
      )
    WHERE i.owner=? AND COALESCE(
        NULLIF(i.work_package_id, ''), i.instance_id
    )=? AND b.is_current_incarnation=1
    ORDER BY b.updated_at DESC, i.graph_version DESC, b.branch_id DESC
    LIMIT ?
"""

BRANCH_DETAIL_SQL = """
    SELECT i.instance_id,
           COALESCE(NULLIF(i.work_package_id, ''), i.instance_id)
               AS work_package_id,
           i.created_by_profile_ref,
           i.current_owner_profile_ref, i.graph_id, i.graph_version,
           i.product_group,
           i.workspace_id, i.mode, i.created_at AS instance_created_at,
           b.branch_id, b.label, b.current_node, b.status,
           b.current_capability_resolution_hash,
           b.current_trial_plan_hash, b.trial_stage_projection_json,
           b.evidence_refs_json, b.omitted_evidence_count,
           b.latest_trace_id, b.created_at, b.updated_at,
           t.edge_id AS latest_trace_edge_id,
           t.from_node AS latest_trace_from_node,
           t.created_at AS latest_trace_created_at,
           t.acting_profile_ref AS latest_trace_acting_profile_ref,
           t.evidence_json AS latest_trace_evidence_json,
           lineage.edge_id AS lineage_edge_id,
           lineage.evidence_json AS lineage_evidence_json
    FROM research_graph_instances AS i
    JOIN research_graph_branches AS b
      ON b.instance_id=i.instance_id
    LEFT JOIN research_graph_trace AS t
      ON t.trace_id=b.latest_trace_id
    LEFT JOIN research_graph_trace AS lineage
      ON lineage.trace_id=(
          SELECT candidate.trace_id
          FROM research_graph_trace AS candidate
          WHERE candidate.instance_id=b.instance_id
            AND candidate.branch_id=b.branch_id
            AND candidate.created_at=b.created_at
            AND candidate.edge_id IN (
                '__branch_fork__', '__graph_continuation__'
            )
          ORDER BY candidate.trace_id
          LIMIT 1
      )
    WHERE i.owner=? AND i.instance_id=? AND b.branch_id=?
"""

WORK_PACKAGE_BRANCH_DETAIL_SQL = BRANCH_DETAIL_SQL.replace(
    "WHERE i.owner=? AND i.instance_id=? AND b.branch_id=?",
    """WHERE i.owner=? AND COALESCE(
        NULLIF(i.work_package_id, ''), i.instance_id
    )=? AND b.branch_id=? AND b.is_current_incarnation=1""",
)
