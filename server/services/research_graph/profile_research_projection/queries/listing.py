"""Bounded list queries for profile-facing Work Package projections."""

LIST_FIRST_SQL = """
    WITH candidates AS (
        SELECT i.instance_id,
               COALESCE(NULLIF(i.work_package_id, ''), i.instance_id)
                   AS work_package_id,
               i.created_by_profile_ref, i.current_owner_profile_ref,
               COALESCE(wp.lifecycle, 'active') AS lifecycle,
               COALESCE(wp.revision, 1) AS lifecycle_revision,
               i.graph_id, i.graph_version, i.product_group,
               i.workspace_id, i.mode,
               COALESCE(wp.title, '') AS title,
               (
                   SELECT MIN(root.created_at)
                   FROM research_graph_instances AS root
                   WHERE root.owner=i.owner AND COALESCE(
                       NULLIF(root.work_package_id, ''), root.instance_id
                   )=COALESCE(NULLIF(i.work_package_id, ''), i.instance_id)
               ) AS instance_created_at,
               COUNT(b.branch_id) OVER (
                   PARTITION BY COALESCE(
                       NULLIF(i.work_package_id, ''), i.instance_id
                   )
               ) AS branch_count,
               SUM(CASE WHEN b.status='running' THEN 1 ELSE 0 END) OVER (
                   PARTITION BY COALESCE(
                       NULLIF(i.work_package_id, ''), i.instance_id
                   )
               ) AS running_branch_count,
               MAX(b.updated_at) OVER (
                   PARTITION BY COALESCE(
                       NULLIF(i.work_package_id, ''), i.instance_id
                   )
               ) AS updated_at,
               ROW_NUMBER() OVER (
                   PARTITION BY COALESCE(
                       NULLIF(i.work_package_id, ''), i.instance_id
                   )
                   ORDER BY b.updated_at DESC, i.graph_version DESC,
                            b.branch_id DESC
               ) AS head_rank
        FROM research_graph_instances AS i
        JOIN research_graph_branches AS b
          ON b.instance_id=i.instance_id
        LEFT JOIN research_work_packages AS wp
          ON wp.owner=i.owner
         AND wp.work_package_id=COALESCE(
             NULLIF(i.work_package_id, ''), i.instance_id
         )
        WHERE i.owner=? AND i.workspace_id=? AND i.mode='live'
          AND b.is_current_incarnation=1
    )
    SELECT * FROM candidates WHERE head_rank=1 AND lifecycle=?
    ORDER BY updated_at DESC, work_package_id DESC
    LIMIT ?
"""

LIST_AFTER_SQL = """
    WITH candidates AS (
        SELECT i.instance_id,
               COALESCE(NULLIF(i.work_package_id, ''), i.instance_id)
                   AS work_package_id,
               i.created_by_profile_ref, i.current_owner_profile_ref,
               COALESCE(wp.lifecycle, 'active') AS lifecycle,
               COALESCE(wp.revision, 1) AS lifecycle_revision,
               i.graph_id, i.graph_version, i.product_group,
               i.workspace_id, i.mode,
               COALESCE(wp.title, '') AS title,
               (
                   SELECT MIN(root.created_at)
                   FROM research_graph_instances AS root
                   WHERE root.owner=i.owner AND COALESCE(
                       NULLIF(root.work_package_id, ''), root.instance_id
                   )=COALESCE(NULLIF(i.work_package_id, ''), i.instance_id)
               ) AS instance_created_at,
               COUNT(b.branch_id) OVER (
                   PARTITION BY COALESCE(
                       NULLIF(i.work_package_id, ''), i.instance_id
                   )
               ) AS branch_count,
               SUM(CASE WHEN b.status='running' THEN 1 ELSE 0 END) OVER (
                   PARTITION BY COALESCE(
                       NULLIF(i.work_package_id, ''), i.instance_id
                   )
               ) AS running_branch_count,
               MAX(b.updated_at) OVER (
                   PARTITION BY COALESCE(
                       NULLIF(i.work_package_id, ''), i.instance_id
                   )
               ) AS updated_at,
               ROW_NUMBER() OVER (
                   PARTITION BY COALESCE(
                       NULLIF(i.work_package_id, ''), i.instance_id
                   )
                   ORDER BY b.updated_at DESC, i.graph_version DESC,
                            b.branch_id DESC
               ) AS head_rank
        FROM research_graph_instances AS i
        JOIN research_graph_branches AS b
          ON b.instance_id=i.instance_id
        LEFT JOIN research_work_packages AS wp
          ON wp.owner=i.owner
         AND wp.work_package_id=COALESCE(
             NULLIF(i.work_package_id, ''), i.instance_id
         )
        WHERE i.owner=? AND i.workspace_id=? AND i.mode='live'
          AND b.is_current_incarnation=1
    )
    SELECT * FROM candidates
    WHERE head_rank=1 AND lifecycle=? AND (
        updated_at<? OR (updated_at=? AND work_package_id<?)
    )
    ORDER BY updated_at DESC, work_package_id DESC
    LIMIT ?
"""
