"""Resolve live product-group references inside setting-template snapshots."""

from __future__ import annotations

from copy import deepcopy


def refresh_template_product_group_paths(template: dict, groups: list[dict]) -> dict:
    """Return a template copy without expanding product-path references."""
    refreshed = deepcopy(template)
    id_by_name = {
        str(group.get('name') or ''): str(group.get('id') or '')
        for group in groups
        if isinstance(group, dict) and group.get('name') and group.get('id')
    }
    snapshot = refreshed.get('snapshot', {})
    selections = []
    execution = snapshot.get("execution") if isinstance(snapshot, dict) else None
    settings = execution.get("settings") if isinstance(execution, dict) else None
    if isinstance(settings, dict) and isinstance(settings.get("product_path_selection"), dict):
        selections.append(settings["product_path_selection"])
    group_settings = snapshot.get("group_settings") if isinstance(snapshot, dict) else None
    if isinstance(group_settings, dict):
        for group in group_settings.get("groups") or []:
            if isinstance(group, dict) and isinstance(group.get("product_path_selection"), dict):
                selections.append(group["product_path_selection"])
    for selection in selections:
        if not isinstance(selection, dict):
            continue
        selection_id = str(
            selection.get('product_path_selection_id')
            or selection.get('selection_id')
            or selection.get('id')
            or selection.get('product_group_template_id')
            or selection.get('path_id')
            or ''
        ).strip()
        paths = selection.get('paths') or selection.get('selected_paths')
        normalized_paths = [
            str(path).strip()
            for path in (paths if isinstance(paths, list) else [])
            if str(path).strip()
        ]
        is_product_group_ref = bool(
            selection.get('product_group_template_id')
            or selection.get('path_id')
            or selection.get('source_type') == 'user_product_group_template'
        )
        if not selection_id:
            product_group = str(selection.get('product_group') or selection.get('label') or '').strip()
            selection_id = id_by_name.get(product_group, '')
            is_product_group_ref = bool(selection_id)
        if selection_id:
            selection.clear()
            selection['product_path_selection_id'] = selection_id
            if normalized_paths and not is_product_group_ref:
                selection['paths'] = normalized_paths
    return refreshed
