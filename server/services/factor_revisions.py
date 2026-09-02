"""Validate formula-addressed factors frozen into immutable RunSpecs."""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from typing import Any

from server.modules.custom_factors.expression_inspection import fixed_column_refs
from server.modules.shared.factor_param_utils import (
    factor_param_value_storage,
    normalize_factor_param_row,
    unique_frozen_factor_records,
)
from server.services.factor_registry import (
    get_factor_family_instance,
    resolve_factor_family_source,
)
from server.services.run_input_inspection import instantiate_factor_metadata
from tools.cli.factor_subject_refs import split_owner_qualified_factor_family
from tools.factors.formula_identity import require_frozen_factor


def freeze_factor_revisions(
    configuration: dict[str, Any],
    *,
    owner: str,
) -> dict[str, Any]:
    """Freeze one canonical, deduplicated factor collection into a RunSpec."""
    frozen = deepcopy(configuration)
    shared = frozen["payload"]["shared"]
    if "factor_revision_manifests" in shared:
        raise ValueError("legacy factor revision manifests are incompatible")
    factors = unique_frozen_factor_records(shared.get("factors"))
    _assert_factors_current(factors, owner=owner)
    _assert_role_factor_refs_frozen(frozen["payload"], factors)
    shared["factors"] = factors
    shared.pop("factor_families", None)
    return frozen


def assert_run_spec_factor_revisions_current(
    run_spec: dict[str, Any],
    *,
    owner: str,
) -> None:
    """Fail closed unless execution resolves the exact frozen formulas."""
    if int(run_spec.get("run_spec_version") or 0) < 3:
        raise ValueError("legacy RunSpec factor identity is incompatible")
    configuration = run_spec.get("configuration")
    shared = (
        configuration.get("shared")
        if isinstance(configuration, dict) else None
    )
    if not isinstance(shared, dict):
        raise ValueError("versioned RunSpec requires configuration.shared")
    if "factor_revision_manifests" in shared:
        raise ValueError("legacy factor revision manifests are incompatible")
    factors = unique_frozen_factor_records(shared.get("factors"))
    if factors != shared.get("factors"):
        raise ValueError("RunSpec factors must be canonically deduplicated")
    _assert_role_factor_refs_frozen(configuration, factors)
    _assert_factors_current(factors, owner=owner)


def _assert_factors_current(
    factors: list[dict[str, Any]],
    *,
    owner: str,
) -> None:
    by_family: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    frozen_by_ref = {item["ref"]: item for item in factors}
    for raw in factors:
        factor = require_frozen_factor(raw)
        identity = factor["identity"]
        if _requires_dependency_aware_validation(raw):
            _assert_dependency_factor_current(
                raw, owner=owner, frozen_by_ref=frozen_by_ref,
            )
            continue
        by_family[(factor["owner_ref"], identity["family_alias"])].append(
            factor
        )

    for (factor_owner, family_alias), members in by_family.items():
        family_ref = f"{factor_owner}:{family_alias}"
        definition = _load_revision_definition(
            family_ref=family_ref,
            factor_aliases=sorted(item["alias"] for item in members),
            owner=owner,
        )
        current = {
            item["factor_alias"]: item
            for item in definition["resolved_factors"]
        }
        for factor in members:
            identity = factor["identity"]
            resolved = current.get(factor["alias"])
            if (
                str(definition["family_formula_fingerprint"])
                != identity["family_formula_fingerprint"]
                or not resolved
                or str(resolved["self_formula_fingerprint"])
                != identity["self_formula_fingerprint"]
                or resolved["params"] != identity["params"]
            ):
                raise ValueError(
                    "factor formula changed after RunSpec freeze; "
                    "preview and submit a new RunSpec; "
                    f"alias={factor['alias']!r}, "
                    "expected_family_formula_fingerprint="
                    f"{identity['family_formula_fingerprint']}, "
                    "current_family_formula_fingerprint="
                    f"{definition['family_formula_fingerprint']}, "
                    "expected_self_formula_fingerprint="
                    f"{identity['self_formula_fingerprint']}, "
                    "current_self_formula_fingerprint="
                    f"{str((resolved or {}).get('self_formula_fingerprint') or '')}"
                )


def _requires_dependency_aware_validation(value: dict[str, Any]) -> bool:
    identity = require_frozen_factor(value)["identity"]
    return (
        str(value.get("source_kind") or "") == "transient"
        or bool(value.get("factor_dependencies"))
        or any(
            isinstance(item, str) and item.startswith("factor:v2:")
            for item in identity["params"].values()
        )
    )


def _assert_dependency_factor_current(
    raw: dict[str, Any], *, owner: str,
    frozen_by_ref: dict[str, dict[str, Any]],
) -> None:
    """Validate nested/inline factors from their frozen dependency graph."""
    frozen = require_frozen_factor(raw)
    identity = frozen["identity"]
    family_alias = identity["family_alias"]
    if str(raw.get("source_kind") or "") == "transient":
        from server.modules.custom_factors.catalog import (
            _load_factor_family_from_source,
        )
        source_code = str(raw.get("source_code") or "").strip()
        if not source_code:
            raise ValueError(f"inline factor source is unavailable: {family_alias}")
        factor_cls, _ = _load_factor_family_from_source(source_code, family_alias)
        if factor_cls is None:
            raise ValueError(f"inline factor source cannot be loaded: {family_alias}")
        family = factor_cls()
    else:
        family = get_factor_family_instance(
            f"{frozen['owner_ref']}:{family_alias}", username=owner,
        )
    if (
        getattr(family, "expr", None) is None
        or family.expr.semantic_fingerprint()
        != identity["family_formula_fingerprint"]
    ):
        raise ValueError(
            "factor family formula changed after RunSpec freeze; "
            f"alias={frozen['alias']!r}"
        )

    from server.modules.shared.factor_param_resolver import (
        resolve_factor_param_value,
    )
    from tools.factors.factor_param_resolution import factor_param_resolver_scope

    with factor_param_resolver_scope(lambda value: resolve_factor_param_value(
        value, username=owner, frozen_by_ref=frozen_by_ref,
    )):
        normalized = normalize_factor_param_row(family, identity["params"])
        factor = family.get_factor(**normalized)
    expression = getattr(factor, "_source_expr", None) or factor.expr
    normalized_storage = {
        parameter.alias: factor_param_value_storage(
            parameter, normalized.get(parameter.alias),
        )
        for parameter in family.params
    }
    if (
        str(factor.alias) != frozen["alias"]
        or expression.semantic_fingerprint()
        != identity["self_formula_fingerprint"]
        or normalized_storage != identity["params"]
    ):
        raise ValueError(
            "factor formula changed after RunSpec freeze; "
            f"alias={frozen['alias']!r}"
        )


def _assert_role_factor_refs_frozen(
    configuration: dict[str, Any],
    factors: list[dict[str, Any]],
) -> None:
    frozen_refs = {item["ref"] for item in factors}
    backtest = (configuration.get("analyses") or {}).get("backtest")
    if not isinstance(backtest, dict):
        return
    for group in backtest.get("groups") or []:
        if not isinstance(group, dict):
            continue
        bindings = group.get("factorRoleBindings")
        if bindings is None:
            bindings = group.get("factor_role_bindings")
        if not isinstance(bindings, dict):
            continue
        for binding in bindings.values():
            if isinstance(binding, dict):
                binding = binding.get("factor_ref") or binding.get("ref")
            factor_ref = str(binding or "").strip()
            if factor_ref and factor_ref not in frozen_refs:
                raise ValueError(
                    f"role-bound factor reference was not frozen: {factor_ref}"
                )


def _load_revision_definition(
    *,
    family_ref: str,
    factor_aliases: list[str],
    owner: str,
) -> dict[str, Any]:
    source = resolve_factor_family_source(family_ref, username=owner)
    family = get_factor_family_instance(family_ref, username=owner)
    if getattr(family, "expr", None) is None:
        raise ValueError(f"factor family formula is unavailable: {family_ref}")
    resolved = []
    for alias in factor_aliases:
        try:
            params = family.parse_alias(alias)
            metadata = instantiate_factor_metadata(family, params)
            factor = family.factor_from_alias(alias)
            if getattr(factor, "expr", None) is None:
                raise ValueError(f"factor formula is unavailable: {alias}")
            column_refs = fixed_column_refs(getattr(factor, "expr", None))
        except ValueError as error:
            raise ValueError(
                f"factor formula cannot be frozen: {alias}"
            ) from error
        resolved.append({
            "factor_alias": alias,
            "self_formula_fingerprint": metadata[
                "self_formula_fingerprint"
            ],
            "params": metadata["normalized_params"],
            "column_refs": sorted(column_refs),
        })
    return {
        **source,
        "factor_owner_ref": (
            split_owner_qualified_factor_family(
                str(source["canonical_family_ref"])
            )[0]
            or ""
        ),
        "factor_family_alias": split_owner_qualified_factor_family(
            str(source["canonical_family_ref"])
        )[1],
        "family_formula_fingerprint": family.expr.semantic_fingerprint(),
        "resolved_factors": resolved,
    }


__all__ = [
    "assert_run_spec_factor_revisions_current",
    "freeze_factor_revisions",
]
