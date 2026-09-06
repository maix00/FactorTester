"""Freeze reusable product-scope objects behind one configuration interface."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any

from server.modules.shared.factor_param_utils import unique_frozen_factor_records

_UI_CATALOG_KEYS = {
    "product_path_candidates",
    "product_group_candidates",
    "product_category_candidates",
    "factor_candidates",
    "factor_family_candidates",
    "factor_set_candidates",
}


def freeze_product_scope(
    configuration: dict[str, Any], *, owner: str, analyses: list[str]
) -> dict[str, Any]:
    """Return a self-contained configuration without mutable catalog snapshots.

    Product selections, category definitions, and source declarations are
    shared immutable inputs. Analysis modules keep only references to them.
    The resulting shape is consumed unchanged by preview and submission.
    """
    frozen = deepcopy(configuration)
    payload = frozen.get("payload")
    if not isinstance(payload, dict):
        return frozen
    shared = payload.setdefault("shared", {})
    analysis_map = payload.get("analyses")
    if not isinstance(shared, dict) or not isinstance(analysis_map, dict):
        return frozen

    temporary = shared.pop("temporary_objects", None)
    temporary = temporary if isinstance(temporary, dict) else {}
    analysis_values = [
        analysis_map.get(kind)
        for kind in analyses
        if isinstance(analysis_map.get(kind), dict)
    ]
    selections: dict[str, dict[str, Any]] = _selection_index(
        shared.pop("product_selections", None)
    )
    for analysis in analysis_values:
        selections.update(_selection_index(analysis.pop("product_selections", None)))
    selections.update(_selection_index(temporary.get("product_selections")))

    referenced_ids = {
        selection_id
        for analysis in analysis_values
        for selection_id in _analysis_selection_ids(analysis)
    }
    embedded = {
        selection_id: selections.get(selection_id)
        or _embedded_selection(analysis_values, selection_id)
        for selection_id in referenced_ids
    }
    # Inline selections are authoritative request objects. Persisted product
    # groups are not: the client submits their stable reference and the origin
    # Manager freezes the owner's current catalog definition. This prevents a
    # stale or forged client-side path projection from becoming execution
    # authority while keeping genuinely inline/template-local scopes portable.
    catalog_refs = {
        selection_id: _catalog_group_reference(selection_id, embedded.get(selection_id))
        for selection_id in referenced_ids
    }
    product_groups = (
        _product_group_index(owner) if any(catalog_refs.values()) else {}
    )
    unresolved: set[str] = set()
    canonical_selections: dict[str, dict[str, Any]] = {}
    for selection_id in sorted(referenced_ids):
        raw = embedded.get(selection_id)
        catalog_ref = catalog_refs.get(selection_id)
        group = product_groups.get(catalog_ref) if catalog_ref else None
        if catalog_ref and not group:
            unresolved.add(selection_id)
            continue
        if group:
            raw = group
        if not raw:
            unresolved.add(selection_id)
            continue
        canonical_selections[selection_id] = _canonical_selection(
            selection_id, raw, group
        )
    if unresolved:
        raise ValueError(
            "configuration references product selections unavailable to owner: "
            + ", ".join(sorted(unresolved))
        )

    category_ids = {
        category_id
        for selection in canonical_selections.values()
        for category_id in selection.get("category_ids") or []
    }
    temporary_categories = _object_index(temporary.get("product_categories"))
    categories = _freeze_categories(
        owner=owner,
        category_ids=category_ids,
        temporary=temporary_categories,
    )
    shared["product_selections"] = canonical_selections
    if categories:
        shared["product_categories"] = categories
    temporary_factors = temporary.get("factors")
    if temporary_factors:
        if not isinstance(temporary_factors, list):
            raise ValueError("temporary factor collection must be a list")
        shared["factors"] = unique_frozen_factor_records([
            *(shared.get("factors") or []),
            *_referenced_temporary_factors(shared.get("factors") or [], temporary_factors),
        ])
    _compact_execution_projections(shared, analysis_map, payload.get("ui"))
    _strip_ui_catalogs(payload.get("ui"))
    return frozen


def _referenced_temporary_factors(roots: list[dict], candidates: list) -> list[dict]:
    """Select the execution dependency closure from the editable candidate pool.

    Unselected drafts may be incomplete. They remain in the authoring workspace
    but must neither become execution subjects nor block unrelated runs.
    """
    by_ref: dict[str, list[dict]] = {}
    for item in candidates:
        if isinstance(item, dict) and item.get("ref"):
            by_ref.setdefault(item["ref"], []).append(item)
    pending = list(roots)
    seen: set[str] = set()
    selected: list[dict] = []

    def references(value):
        if isinstance(value, str) and value.startswith("factor:v2:"):
            yield value
        elif isinstance(value, dict):
            for child in value.values():
                yield from references(child)
        elif isinstance(value, list):
            for child in value:
                yield from references(child)

    while pending:
        record = pending.pop()
        refs = [record.get("ref"), *references(record.get("identity", {}).get("params"))]
        pending.extend(record.get("factor_dependencies") or [])
        for ref in refs:
            if not ref or ref in seen:
                continue
            seen.add(ref)
            matches = by_ref.get(ref, [])
            selected.extend(matches)
            pending.extend(matches)
    return selected


def _compact_execution_projections(
    shared: dict[str, Any], analyses: dict[str, Any], ui: object
) -> None:
    """Delete aliases that repeat the same frozen semantic value."""
    for analysis in analyses.values():
        if not isinstance(analysis, dict):
            continue
        execution = analysis.get("execution")
        execution_settings = (
            execution.get("settings") if isinstance(execution, dict) else None
        )
        if isinstance(execution_settings, dict):
            for key, value in tuple(execution_settings.items()):
                if key in analysis and analysis[key] == value:
                    analysis.pop(key, None)
        if "local_settings" in analysis or "settings" in analysis:
            raise ValueError(
                "legacy analysis settings are incompatible; rebuild this RunSpec"
            )
        for group in analysis.get("groups") or []:
            if not isinstance(group, dict):
                continue
            selection_id = _selection_id(group)
            if selection_id:
                group["product_path_selection_id"] = selection_id
                embedded_selection = group.get("product_path_selection")
                if isinstance(embedded_selection, dict):
                    embedded_selection["product_path_selection_id"] = selection_id
            for legacy_key in (
                "factorAlias", "factorAliases", "factor_alias", "factor_aliases",
            ):
                group.pop(legacy_key, None)
    for factor in shared.get("factors") or []:
        if not isinstance(factor, dict):
            continue
        for canonical, duplicate in (
            ("factor_owner_ref", "owner_ref"),
            ("factor_params", "params"),
        ):
            if canonical in factor and factor.get(duplicate) == factor[canonical]:
                factor.pop(duplicate, None)
    if isinstance(ui, dict):
        for state in ui.values():
            if isinstance(state, dict):
                state.pop("settings", None)


def _selection_id(group: dict[str, Any]) -> str:
    embedded = group.get("product_path_selection")
    if isinstance(embedded, dict):
        return str(
            embedded.get("product_path_selection_id")
            or embedded.get("selection_id")
            or embedded.get("id")
            or embedded.get("group_ref")
            or embedded.get("product_group_ref")
            or embedded.get("product_group_template_id")
            or ""
        ).strip()
    return str(
        group.get("product_path_selection_id")
        or group.get("product_scope_ref")
        or group.get("product_group_ref")
        or group.get("testerId")
        or ""
    ).strip()


def _analysis_selection_ids(analysis: dict[str, Any]) -> set[str]:
    result = {
        str(analysis.get(key) or "").strip()
        for key in ("product_path_selection_id", "selection_id")
        if str(analysis.get(key) or "").strip()
    }
    for group in analysis.get("groups") or []:
        if isinstance(group, dict) and _selection_id(group):
            result.add(_selection_id(group))
    # IC schema 2 keeps product scope ownership on each typed configuration
    # group; it is intentionally not flattened into a global analysis field.
    for group in analysis.get("configuration_groups") or []:
        if not isinstance(group, dict):
            continue
        selection_id = str(group.get("product_scope_ref") or "").strip()
        if selection_id:
            result.add(selection_id)
    return result


def _embedded_selection(
    analyses: list[dict[str, Any]], selection_id: str
) -> dict:
    for analysis in analyses:
        direct = analysis.get("product_path_selection")
        if isinstance(direct, dict) and _selection_id(direct) == selection_id:
            return deepcopy(direct)
        for group in analysis.get("groups") or []:
            if isinstance(group, dict) and _selection_id(group) == selection_id:
                value = group.get("product_path_selection")
                return deepcopy(value) if isinstance(value, dict) else {}
    return {}


def _selection_index(value: object) -> dict[str, dict[str, Any]]:
    if isinstance(value, dict):
        return {
            str(key): deepcopy(item)
            for key, item in value.items()
            if isinstance(item, dict)
        }
    if not isinstance(value, list):
        return {}
    result = {}
    for item in value:
        if not isinstance(item, dict):
            continue
        key = str(
            item.get("product_path_selection_id")
            or item.get("selection_id")
            or item.get("id")
            or ""
        ).strip()
        if key:
            result[key] = deepcopy(item)
    return result


def _object_index(value: object) -> dict[str, dict[str, Any]]:
    if isinstance(value, dict):
        return {
            str(key): deepcopy(item)
            for key, item in value.items()
            if isinstance(item, dict)
        }
    if isinstance(value, list):
        return {
            str(item.get("id") or ""): deepcopy(item)
            for item in value
            if isinstance(item, dict) and str(item.get("id") or "").strip()
        }
    return {}


def _product_group_index(owner: str) -> dict[str, dict[str, Any]]:
    from server.modules.products.product_group_store import (
        load_authoritative_product_groups,
    )

    result = {}
    for item in load_authoritative_product_groups(owner):
        if not isinstance(item, dict):
            continue
        raw_id = str(item.get("id") or "").strip()
        if not raw_id:
            continue
        result[raw_id] = item
        result.setdefault(f"product-group:{raw_id}", item)
    return result


def _catalog_group_reference(
    selection_id: str,
    raw: dict[str, Any] | None,
) -> str:
    """Return the owner-catalog key when a selection claims catalog identity."""
    source = raw if isinstance(raw, dict) else {}
    template_ref = str(
        source.get("product_group_template_id")
        or source.get("product_group_ref")
        or ""
    ).strip()
    source_type = str(source.get("source_type") or "").strip()
    candidates = (template_ref, str(selection_id or "").strip())
    for candidate in candidates:
        if candidate.startswith("product-group:"):
            return candidate
    if source_type == "user_product_group_template":
        return template_ref or str(selection_id or "").strip()
    # A reference without an embedded definition is the legacy catalog form.
    if not source or not (source.get("paths") or source.get("selected_paths")):
        return template_ref or str(selection_id or "").strip()
    return ""


def _canonical_selection(
    selection_id: str,
    raw: dict[str, Any],
    stored_group: dict[str, Any] | None,
) -> dict[str, Any]:
    # Once a catalog group is resolved, every execution-semantic field comes
    # from that owner-controlled row. Client projections remain input/display
    # hints only and cannot override paths or category bindings.
    source = dict(stored_group) if stored_group else dict(raw)
    paths = (
        source.get("paths")
        or source.get("selected_paths")
        or (stored_group or {}).get("paths")
        or (stored_group or {}).get("selected_paths")
        or []
    )
    if not isinstance(paths, list) or not paths:
        raise ValueError(f"product selection has no paths: {selection_id}")
    result = {
        "id": selection_id,
        "label": str(
            source.get("label")
            or source.get("name")
            or source.get("product_group")
            or selection_id
        ),
        "paths": list(dict.fromkeys(
            str(path).strip() for path in paths if str(path).strip()
        )),
    }
    category_ids = list(dict.fromkeys(
        str(value).strip()
        for value in source.get("category_ids") or []
        if str(value).strip()
    ))
    if category_ids:
        result["category_ids"] = category_ids
    result["origin"] = str(source.get("origin") or (
        "catalog" if stored_group else "inline"
    ))
    template_id = str(
        source.get("product_group_template_id") or ""
    ).strip()
    if not template_id and stored_group:
        template_id = str(stored_group.get("id") or selection_id).strip()
    if template_id:
        result["product_group_template_id"] = template_id
    return result


def _freeze_categories(
    *, owner: str, category_ids: set[str], temporary: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    if not category_ids:
        return {}
    from server.modules.products.product_category_store import list_product_categories

    available = {
        str(item.get("id") or ""): item
        for item in list_product_categories(owner)
        if isinstance(item, dict)
    }
    available.update(temporary)
    missing = sorted(category_ids - set(available))
    if missing:
        raise ValueError("product categories unavailable to owner: " + ", ".join(missing))
    return {
        category_id: _stable_category(
            available[category_id], include_items=category_id in temporary
        )
        for category_id in sorted(category_ids)
    }


def _stable_category(
    value: dict[str, Any], *, include_items: bool
) -> dict[str, Any]:
    allowed = (
        "id", "alias", "title_zh", "kind", "owner_ref", "source_ids",
        "dimensions", "composable", "is_composite", "parent_category_ids",
    )
    result = {
        key: deepcopy(value[key])
        for key in allowed
        if key in value
    }
    items = deepcopy(value.get("items") or [])
    result["definition_sha256"] = hashlib.sha256(json.dumps(
        items, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()
    if include_items:
        result["items"] = items
    return result


def _strip_ui_catalogs(value: object) -> None:
    if isinstance(value, dict):
        for key in tuple(value):
            if key in _UI_CATALOG_KEYS:
                value.pop(key, None)
            else:
                _strip_ui_catalogs(value[key])
    elif isinstance(value, list):
        for item in value:
            _strip_ui_catalogs(item)
