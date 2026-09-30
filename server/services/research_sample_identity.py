"""Server-derived sample identity from an immutable ResearchRun RunSpec.

This module intentionally has no Research Graph or TrialPlan dependencies so
the sample scope remains valid after the Graph product is retired.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import orjson


_UNIVERSE_KEYS = {"paths", "products", "selected_paths"}
_CONTEXT_KEYS = {
    "end_time",
    "frequency",
    "ic_lag",
    "return_price_basis",
    "signal_freq",
    "start_time",
    "time_precision",
    "timezone",
}
_COSMETIC_KEYS = {"desc", "description", "label"}
_PRODUCT_SCOPE_REFERENCE_KEYS = {
    "product_scope_ref",
    "product_path_selection_id",
}


def derive_sample_identity(run_spec: dict[str, Any]) -> dict[str, Any]:
    """Hash one exact date/universe scope without assigning a sample role."""
    if not isinstance(run_spec, dict):
        raise ValueError("RunSpec must be an object")
    scopes = _execution_scopes(run_spec)
    starts: set[str] = set()
    ends: set[str] = set()
    universes: list[Any] = []
    scope_members: list[str] = []
    referenced_selections: set[str] = set()
    membership_proven = True
    context: list[tuple[str, Any]] = []
    for scope_name, scope in scopes.items():
        module_universes: dict[str, list[Any]] = {
            "selected_paths": [],
            "paths": [],
            "products": [],
        }
        _collect_scope(
            scope,
            path=f"execution_scope.{scope_name}",
            starts=starts,
            ends=ends,
            universes=module_universes,
            context=context,
        )
        universes.extend(_preferred_universe(module_universes))
        referenced_selections.update(_product_scope_references(scope))
        raw_members = _preferred_universe(module_universes)
        for member in raw_members:
            if isinstance(member, str) and _is_concrete_product_path(member):
                scope_members.append(member)
            elif (
                not isinstance(member, str)
                or member not in _PRODUCT_SCOPE_REFERENCE_KEYS
            ):
                membership_proven = False
    if not starts or not ends:
        raise ValueError(
            "RunSpec cannot derive sample identity without start/end dates"
        )
    if len(starts) != 1 or len(ends) != 1:
        raise ValueError(
            "RunSpec sample identity requires one unambiguous date range"
        )
    frozen_members, frozen_members_proven = _frozen_product_members(
        run_spec, referenced_selections,
    )
    if referenced_selections:
        if not frozen_members_proven:
            membership_proven = False
        else:
            scope_members.extend(frozen_members)
    if not universes and frozen_members_proven and frozen_members:
        # Referenced frozen scopes are the canonical RunSpec representation;
        # use their exact leaf set when older path projections are absent.
        universes.extend(frozen_members)
    if not universes:
        raise ValueError(
            "RunSpec cannot derive sample identity without product scope"
        )
    sample_start = next(iter(starts))
    sample_end = next(iter(ends))
    if sample_start > sample_end:
        raise ValueError("RunSpec sample date range is invalid")
    normalized_universes = _deduplicate(universes)
    normalized_members = sorted(set(scope_members))
    if not normalized_members:
        membership_proven = False
    universe_hash = _hash(normalized_universes)
    sample_basis = {
        "schema_version": 1,
        "sample_start": sample_start,
        "sample_end": sample_end,
        "universe_hash": universe_hash,
    }
    return {
        **sample_basis,
        "sample_hash": _hash(sample_basis),
        "design_context_hash": _hash(sorted(context)),
        "authority": "server_derived_scope_v1",
        "universe_members": normalized_members if membership_proven else [],
        "universe_membership_assurance": (
            "exact_frozen_product_scope" if membership_proven else "not_proven"
        ),
        "limitations": [
            "data_snapshot_identity_not_bound",
            "external_result_access_not_observable",
            *([] if membership_proven else ["product_membership_not_proven"]),
        ],
    }


def _product_scope_references(value: Any) -> set[str]:
    references: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key in _PRODUCT_SCOPE_REFERENCE_KEYS and isinstance(item, str):
                normalized = item.strip()
                if normalized:
                    references.add(normalized)
            references.update(_product_scope_references(item))
    elif isinstance(value, list):
        for item in value:
            references.update(_product_scope_references(item))
    return references


def _frozen_product_members(
    run_spec: dict[str, Any], references: set[str],
) -> tuple[list[str], bool]:
    if not references:
        return [], True
    configuration = run_spec.get("configuration")
    shared = configuration.get("shared") if isinstance(configuration, dict) else None
    selections = shared.get("product_selections") if isinstance(shared, dict) else None
    if not isinstance(selections, dict):
        return [], False
    members: set[str] = set()
    for reference in references:
        selection = selections.get(reference)
        if not isinstance(selection, dict):
            return [], False
        paths = selection.get("paths")
        if (
            not isinstance(paths, list)
            or not paths
            or any(
                not isinstance(path, str)
                or not path.strip()
                or path != path.strip()
                or not _is_concrete_product_path(path)
                for path in paths
            )
            or len(set(paths)) != len(paths)
        ):
            return [], False
        expected_resolution = hashlib.sha256(
            json.dumps(
                paths, ensure_ascii=False, separators=(",", ":"),
            ).encode()
        ).hexdigest()
        if str(selection.get("resolution_sha256") or "") != expected_resolution:
            return [], False
        members.update(paths)
    return sorted(members), bool(members)


def _is_concrete_product_path(value: str) -> bool:
    normalized = value.strip()
    return (
        bool(normalized)
        and "/_products/" in normalized
        and not normalized.startswith("-")
    )


def _execution_scopes(run_spec: dict[str, Any]) -> dict[str, Any]:
    """Return only the analysis modules executed by this immutable RunSpec."""
    if int(run_spec.get("run_spec_version") or 1) < 2:
        return {"legacy": run_spec}
    analyses = run_spec.get("analyses")
    configuration = run_spec.get("configuration")
    if not isinstance(analyses, list) or not analyses:
        raise ValueError("RunSpec v2 sample identity requires analyses")
    if not isinstance(configuration, dict):
        raise ValueError("RunSpec v2 sample identity requires configuration")
    configured = configuration.get("analyses")
    if not isinstance(configured, dict):
        raise ValueError(
            "RunSpec v2 sample identity requires configuration analyses"
        )
    selected: dict[str, Any] = {}
    for raw_kind in analyses:
        kind = str(raw_kind or "").strip()
        module = configured.get(kind)
        if not kind or not isinstance(module, dict):
            raise ValueError(
                f"RunSpec v2 sample identity missing analysis module: {kind}"
            )
        selected[kind] = module
    return selected


def _preferred_universe(candidates: dict[str, list[Any]]) -> list[Any]:
    """Choose the most explicit universe representation within one module."""
    for key in ("selected_paths", "paths", "products"):
        values = candidates[key]
        if values:
            return values
    return []


def _collect_scope(
    value: Any,
    *,
    path: str,
    starts: set[str],
    ends: set[str],
    universes: dict[str, list[Any]],
    context: list[tuple[str, Any]],
) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            child_path = f"{path}.{key}"
            if key == "start_date" and isinstance(item, str) and item:
                starts.add(item)
            elif key == "end_date" and isinstance(item, str) and item:
                ends.add(item)
            elif key in _UNIVERSE_KEYS and isinstance(item, list) and item:
                universes[key].extend(
                    _semantic_value(element) for element in item
                )
            elif key in _CONTEXT_KEYS:
                context.append((key, _semantic_value(item)))
            _collect_scope(
                item,
                path=child_path,
                starts=starts,
                ends=ends,
                universes=universes,
                context=context,
            )
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _collect_scope(
                item,
                path=f"{path}[{index}]",
                starts=starts,
                ends=ends,
                universes=universes,
                context=context,
            )


def _semantic_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _semantic_value(item)
            for key, item in sorted(value.items())
            if str(key) not in _COSMETIC_KEYS
        }
    if isinstance(value, list):
        normalized = [_semantic_value(item) for item in value]
        return sorted(normalized, key=_encoded)
    return value


def _deduplicate(values: list[Any]) -> list[Any]:
    by_payload = {_encoded(value): value for value in values}
    return [by_payload[key] for key in sorted(by_payload)]


def _encoded(value: Any) -> bytes:
    return orjson.dumps(value, option=orjson.OPT_SORT_KEYS)


def _hash(value: Any) -> str:
    return hashlib.sha256(_encoded(value)).hexdigest()
