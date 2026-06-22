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
    snapshot = refreshed.get('snapshot', {})
    selections = []
    local_settings = snapshot.get("local_settings") if isinstance(snapshot, dict) else None
    if isinstance(local_settings, dict) and isinstance(local_settings.get("product_path_selection"), dict):
        selections.append(local_settings["product_path_selection"])
    group_settings = snapshot.get("group_settings") if isinstance(snapshot, dict) else None
    if isinstance(group_settings, dict):
        for group in group_settings.get("groups") or []:
            if isinstance(group, dict) and isinstance(group.get("product_path_selection"), dict):
                selections.append(group["product_path_selection"])
    for selection in selections:
        if not isinstance(selection, dict):
            continue
        product_group = selection.get('product_group')
        product_group_template_id = selection.get('product_group_template_id')
        current_paths = None
        if product_group_template_id:
            for group in groups:
                if isinstance(group, dict) and group.get("id") == product_group_template_id:
                    current_paths = list(group.get("paths", []))
                    break
        if current_paths is None and product_group and product_group in paths_by_name:
            current_paths = list(paths_by_name[product_group])
        if current_paths is None:
            continue
        selection['paths'] = current_paths
        selection['selected_paths'] = list(current_paths)
    return refreshed
