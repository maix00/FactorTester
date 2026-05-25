"""Resolve live product-group references inside setting-template snapshots."""

from __future__ import annotations

from copy import deepcopy


def refresh_template_product_group_paths(template: dict, groups: list[dict]) -> dict:
    """Return a template copy whose referenced groups use their current paths."""
    refreshed = deepcopy(template)
    paths_by_name = {
        group.get('name'): list(group.get('paths', []))
        for group in groups
        if isinstance(group, dict) and group.get('name')
    }
    submissions = refreshed.get('snapshot', {}).get('submissions', [])
    for submission in submissions:
        if not isinstance(submission, dict):
            continue
        product_group = submission.get('product_group')
        if not product_group or product_group not in paths_by_name:
            continue
        current_paths = list(paths_by_name[product_group])
        submission['paths'] = current_paths
        submission['selected_paths'] = list(current_paths)
    return refreshed
