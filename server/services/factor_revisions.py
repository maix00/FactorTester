"""Opaque factor implementation identities for immutable research RunSpecs."""

from __future__ import annotations

from copy import deepcopy
import hashlib
from typing import Any

import orjson

from server.modules.shared.param_meta import serialize_param_meta
from server.services.factor_registry import (
    factor_from_alias,
    get_factor_family_instance,
    resolve_factor_family_source,
)
from server.modules.custom_factors.expression_inspection import fixed_column_refs
from tools.factors.FactorExpr import get_visual_operator_groups


SCHEMA_VERSION = 1


def freeze_factor_revisions(
    configuration: dict[str, Any],
    *,
    owner: str,
) -> dict[str, Any]:
    """Freeze source-free manifests without mutating editable configuration."""
    frozen = deepcopy(configuration)
    shared = frozen["payload"]["shared"]
    shared["factor_revision_manifests"] = build_factor_revision_manifests(
        shared=shared,
        owner=owner,
        extra_factor_aliases=_role_factor_aliases(frozen["payload"]),
    )
    return frozen


def build_factor_revision_manifests(
    *,
    shared: dict[str, Any],
    owner: str,
    extra_factor_aliases: list[str] | tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    families = shared.get("factor_families")
    factors = shared.get("factors")
    if not isinstance(families, list) or not isinstance(factors, list):
        raise ValueError("factor revision requires canonical shared factors")
    operator_hash = _hash_json(get_visual_operator_groups())
    aliases_by_family: dict[str, set[str]] = {}
    for family in families:
        family_ref = str(
            family.get("alias") if isinstance(family, dict) else ""
        ).strip()
        if family_ref:
            aliases_by_family.setdefault(family_ref, set())
    for item in factors:
        if not isinstance(item, dict):
            continue
        family_ref = str(item.get("factor_family_alias") or "").strip()
        alias = str(item.get("alias") or "").strip()
        if family_ref and alias:
            aliases_by_family.setdefault(family_ref, set()).add(alias)
    for alias in extra_factor_aliases:
        value = str(alias or "").strip()
        family_ref = value.split("|", 1)[0]
        if value and family_ref:
            aliases_by_family.setdefault(family_ref, set()).add(value)

    manifests: list[dict[str, Any]] = []
    for family_ref, aliases in aliases_by_family.items():
        definition = _load_revision_definition(
            family_ref=family_ref,
            factor_aliases=sorted(aliases),
            owner=owner,
        )
        manifests.extend(_manifests_from_definition(
            definition,
            operator_registry_hash=operator_hash,
        ))
    return sorted(
        manifests,
        key=lambda item: (
            item["factor_family_ref"],
            item["factor_alias_hash"],
        ),
    )


def assert_run_spec_factor_revisions_current(
    run_spec: dict[str, Any],
    *,
    owner: str,
) -> None:
    """Fail closed when a v2 RunSpec no longer matches executable factors."""
    if int(run_spec.get("run_spec_version") or 0) < 2:
        return
    configuration = run_spec.get("configuration")
    shared = (
        configuration.get("shared")
        if isinstance(configuration, dict) else None
    )
    if not isinstance(shared, dict):
        raise ValueError("RunSpec v2 requires configuration.shared")
    stored = shared.get("factor_revision_manifests")
    families = shared.get("factor_families")
    if not isinstance(stored, list) or (
        isinstance(families, list) and families and not stored
    ):
        raise ValueError(
            "RunSpec v2 requires factor_revision_manifests"
        )
    current = build_factor_revision_manifests(
        shared=shared,
        owner=owner,
        extra_factor_aliases=_role_factor_aliases(configuration),
    )
    if _execution_identity_manifests(current) != _execution_identity_manifests(stored):
        raise ValueError(
            "factor revision changed after RunSpec freeze; "
            "preview and submit a new RunSpec"
        )


def _load_revision_definition(
    *,
    family_ref: str,
    factor_aliases: list[str],
    owner: str,
) -> dict[str, Any]:
    source = resolve_factor_family_source(
        family_ref,
        username=owner,
    )
    family = get_factor_family_instance(family_ref, username=owner)
    family_tree = (
        family.expr.tree_repr()
        if getattr(family, "expr", None) is not None else ""
    )
    family_columns = fixed_column_refs(getattr(family, "expr", None))
    resolved = []
    for alias in factor_aliases:
        qualified_alias = _qualified_factor_alias(
            alias,
            canonical_family_ref=source["canonical_family_ref"],
        )
        try:
            factor = factor_from_alias(qualified_alias, username=owner)
            tree_repr = (
                factor.expr.tree_repr()
                if getattr(factor, "expr", None) is not None else ""
            )
            column_refs = fixed_column_refs(getattr(factor, "expr", None))
            resolution_status = "resolved"
        except ValueError:
            # Existing configurations may retain superseded parameter aliases.
            # Preserve their exact alias hash and family contract without
            # claiming that factor-level semantics were resolved.
            tree_repr = family_tree
            column_refs = family_columns
            resolution_status = "family_contract_only"
        resolved.append({
            "factor_alias": alias,
            "tree_repr": tree_repr,
            "resolution_status": resolution_status,
            "column_refs": sorted(column_refs),
        })
    if not resolved:
        resolved.append({
            "factor_alias": "",
            "tree_repr": family_tree,
            "resolution_status": "family_contract_only",
            "column_refs": sorted(family_columns),
        })
    return {
        **source,
        "family_tree_repr": family_tree,
        "parameter_schema": [
            _parameter_contract(serialize_param_meta(param))
            for param in family.params
        ],
        "resolved_factors": resolved,
    }


def _manifests_from_definition(
    definition: dict[str, Any],
    *,
    operator_registry_hash: str,
) -> list[dict[str, Any]]:
    family_ref = str(definition["canonical_family_ref"])
    source_policy = str(definition.get("source_mode") or "") or (
        "public"
        if definition["source_kind"] == "public" else "owner_only"
    )
    common = {
        "schema_version": SCHEMA_VERSION,
        "factor_family_ref": family_ref,
        "source_access_policy": source_policy,
        "family_source_hash": _hash_text(definition["source_code"]),
        "family_expr_hash": _hash_text(definition["family_tree_repr"]),
        "parameter_schema_hash": _hash_json(
            definition["parameter_schema"]
        ),
        "operator_registry_hash": operator_registry_hash,
    }
    family_revision_hash = _hash_json(common)
    values = []
    for factor in definition["resolved_factors"]:
        value = {
            **common,
            "family_revision_hash": family_revision_hash,
            "factor_alias_hash": _hash_text(factor["factor_alias"]),
            "resolved_factor_expr_hash": _hash_text(
                factor["tree_repr"]
            ),
            "resolution_status": str(
                factor.get("resolution_status") or "resolved"
            ),
        }
        value["manifest_hash"] = _hash_json(value)
        # Auditable dependency metadata is deliberately outside the execution
        # identity hash: resolved_factor_expr_hash already owns semantics, and
        # adding this projection must not invalidate historical RunSpecs.
        value["column_refs"] = sorted({
            str(item) for item in factor.get("column_refs", [])
        })
        values.append(value)
    return values


def _execution_identity_manifests(value: Any) -> Any:
    if not isinstance(value, list):
        return value
    return [
        {key: item for key, item in manifest.items() if key != "column_refs"}
        if isinstance(manifest, dict) else manifest
        for manifest in value
    ]


def _qualified_factor_alias(
    alias: str,
    *,
    canonical_family_ref: str,
) -> str:
    family = str(alias).split("|", 1)[0]
    if ":" in family:
        return alias
    suffix = alias[len(family):]
    return canonical_family_ref + suffix


def _role_factor_aliases(configuration: dict[str, Any]) -> list[str]:
    """Return source-free aliases bound to strategy roles in a RunSpec.

    These aliases are intentionally not added to ``shared.factors``: a role
    may be resolved from a Profile's transient run source.  They still need a
    frozen revision manifest so the worker can fail closed if its transient
    source differs from the RunSpec it is executing.
    """
    backtest = (configuration.get("analyses") or {}).get("backtest")
    if not isinstance(backtest, dict):
        return []
    aliases: set[str] = set()
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
                binding = (
                    binding.get("factorAlias")
                    or binding.get("factor_alias")
                    or binding.get("alias")
                )
            if isinstance(binding, str) and binding.strip():
                aliases.add(binding.strip())
    return sorted(aliases)


def _parameter_contract(metadata: dict[str, Any]) -> dict[str, Any]:
    """Remove generated display identities from the semantic parameter hash."""
    return {
        "alias": str(metadata.get("alias") or ""),
        "type": str(metadata.get("type") or ""),
        "default_value": metadata.get("default_value"),
        "allowed_values": [
            item.get("value")
            for item in metadata.get("options") or []
            if isinstance(item, dict) and "value" in item
        ],
    }


def _hash_text(value: Any) -> str:
    return hashlib.sha256(str(value).encode()).hexdigest()


def _hash_json(value: Any) -> str:
    return hashlib.sha256(
        orjson.dumps(value, option=orjson.OPT_SORT_KEYS)
    ).hexdigest()
