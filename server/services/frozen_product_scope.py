"""Freeze reusable product-scope objects behind one configuration interface."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any


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
    selections: dict[str, dict[str, Any]] = {}
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
    # A self-contained RunSpec must not consult mutable catalog storage when
    # the selected paths are already frozen in the request. Only unresolved
    # references need the owner's persisted product-group catalog.
    product_groups = (
        _product_group_index(owner)
        if any(
            not isinstance(value, dict)
            or not (value.get("paths") or value.get("selected_paths"))
            for value in embedded.values()
        )
        else {}
    )
    unresolved: set[str] = set()
    canonical_selections: dict[str, dict[str, Any]] = {}
    for selection_id in sorted(referenced_ids):
        raw = embedded.get(selection_id)
        group = product_groups.get(selection_id)
        if not raw and group:
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
    source_ids = {
        source_id
        for category in categories.values()
        for source_id in category.get("source_ids") or []
    }
    temporary_sources = _object_index(
        temporary.get("data_source_declarations")
    )

    shared["product_selections"] = canonical_selections
    if categories:
        shared["product_categories"] = categories
    if source_ids:
        shared["data_source_declarations"] = _freeze_source_declarations(
            source_ids, temporary_sources
        )
    backtest = analysis_map.get("backtest")
    if isinstance(backtest, dict):
        _compact_execution_projections(shared, backtest, payload.get("ui"))
    _strip_ui_catalogs(payload.get("ui"))
    return frozen


def _compact_execution_projections(
    shared: dict[str, Any], backtest: dict[str, Any], ui: object
) -> None:
    """Delete aliases that repeat the same frozen semantic value."""
    local_settings = backtest.get("local_settings")
    if isinstance(local_settings, dict):
        for key, value in tuple(local_settings.items()):
            if key in backtest and backtest[key] == value:
                backtest.pop(key, None)
    for group in backtest.get("groups") or []:
        if not isinstance(group, dict):
            continue
        for legacy_key in (
            "factorAlias", "factorAliases", "factor_alias", "factor_aliases",
        ):
            group.pop(legacy_key, None)
    for factor in shared.get("factors") or []:
        if not isinstance(factor, dict):
            continue
        for canonical, duplicate in (
            ("factor_owner_ref", "owner_ref"),
            ("factor_family_ref", "family_ref"),
            ("factor_params", "params"),
            ("factor_git_commit", "git_commit"),
        ):
            if canonical in factor and factor.get(duplicate) == factor[canonical]:
                factor.pop(duplicate, None)
    if isinstance(ui, dict):
        backtest_ui = ui.get("backtest")
        if isinstance(backtest_ui, dict):
            backtest_ui.pop("settings", None)


def _selection_id(group: dict[str, Any]) -> str:
    embedded = group.get("product_path_selection")
    if isinstance(embedded, dict):
        return str(
            embedded.get("product_path_selection_id")
            or embedded.get("selection_id")
            or embedded.get("id")
            or ""
        ).strip()
    return str(
        group.get("product_path_selection_id")
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
    from server.modules.products.product_group_store import load_product_groups

    result = {}
    for item in load_product_groups(owner):
        if not isinstance(item, dict):
            continue
        raw_id = str(item.get("id") or "").strip()
        if not raw_id:
            continue
        result[raw_id] = item
        result.setdefault(f"product-group:{raw_id}", item)
    return result


def _canonical_selection(
    selection_id: str,
    raw: dict[str, Any],
    stored_group: dict[str, Any] | None,
) -> dict[str, Any]:
    source = {**(stored_group or {}), **raw}
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


def _freeze_source_declarations(
    source_ids: set[str], temporary: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    from server.services.product_catalog_projection import product_source_descriptors

    available = {
        str(item.get("id") or ""): item
        for item in product_source_descriptors()
        if isinstance(item, dict)
    }
    available.update(temporary)
    missing = sorted(source_ids - set(available))
    if missing:
        raise ValueError("data-source declarations unavailable: " + ", ".join(missing))
    return {
        source_id: _stable_source_declaration(available[source_id])
        for source_id in sorted(source_ids)
    }


def _stable_source_declaration(value: dict[str, Any]) -> dict[str, Any]:
    direct = (
        "id", "family_id", "family_name", "source_ref", "source_name",
        "source_kind", "provider_kind", "bundle_id", "bundle_name",
        "server_provided", "naming_schemes", "data_modes", "frequency",
        "timezone", "mapping_revision",
    )
    result = {
        key: deepcopy(value[key])
        for key in direct
        if key in value
    }
    members = []
    for item in value.get("members") or []:
        if not isinstance(item, dict):
            continue
        members.append({
            key: deepcopy(item[key])
            for key in (
                "id", "source_ref", "label", "frequency", "timezone",
                "time_columns", "data_columns", "dimensions", "data_modes",
                "naming_scheme",
            )
            if key in item
        })
    if members:
        result["members"] = members
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
