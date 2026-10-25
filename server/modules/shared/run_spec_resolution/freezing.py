"""Freeze configuration objects through one shared RunSpec input pipeline."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any


def freeze_run_spec_inputs(
    configuration: dict[str, Any], *, owner: str, analyses: list[str],
) -> dict[str, Any]:
    """Freeze every library-backed object required by selected analyses.

    Analysis modules declare references in their configuration.  This pipeline
    alone expands product scopes, external artifacts and the complete factor
    dependency graph before an immutable RunSpec is constructed.
    """
    from server.services.frozen_product_scope import freeze_product_scope
    from server.services import external_factor_artifacts, factor_revisions

    frozen = freeze_product_scope(
        configuration, owner=owner, analyses=analyses,
    )
    frozen = deepcopy(frozen)
    shared = frozen["payload"]["shared"]
    artifacts = external_factor_artifacts.freeze_configured_artifacts(shared)
    if artifacts:
        shared["external_factor_artifacts"] = artifacts
    return factor_revisions.freeze_factor_revisions(frozen, owner=owner)


def freeze_nautilus_execution_policy(configuration: dict[str, Any]) -> dict[str, Any]:
    """Replace Nautilus editor presets with a compact immutable policy.

    The RunSpec refers to already frozen product selections. It never stores
    their expanded instrument universe: defaults cover the selected scope,
    product-selection references carry group overrides, and only explicit
    instrument exceptions are serialized.
    """
    frozen = deepcopy(configuration)
    payload = frozen.get("payload")
    if not isinstance(payload, dict):
        return frozen
    analyses = payload.get("analyses")
    backtest = analyses.get("backtest") if isinstance(analyses, dict) else None
    if not isinstance(backtest, dict):
        return frozen
    execution = backtest.get("execution")
    if not isinstance(execution, dict) or execution.get("backend") != "nautilus_trader":
        return frozen
    settings = execution.get("settings")
    if not isinstance(settings, dict):
        raise ValueError("NautilusTrader execution.settings must be an object")
    if "instrument_ids" in settings:
        raise ValueError(
            "NautilusTrader RunSpec must use frozen product-scope references, not an expanded instrument_ids list"
        )

    scopes = _backtest_product_scope_refs(backtest)
    selections = (payload.get("shared") or {}).get("product_selections")
    if not isinstance(selections, dict) or not scopes:
        raise ValueError(
            "NautilusTrader RunSpec requires at least one frozen product-group selection"
        )
    missing = set(scopes) - set(selections)
    if missing:
        raise ValueError(
            "NautilusTrader product-scope references are not frozen: "
            + ", ".join(sorted(missing))
        )

    requested_scopes = settings.get("product_scope_refs")
    if requested_scopes is not None:
        if (not isinstance(requested_scopes, list)
                or set(map(str, requested_scopes)) != set(scopes)):
            raise ValueError(
                "execution.settings.product_scope_refs must match the backtest's frozen product selections"
            )
    settings["product_scope_refs"] = list(scopes)

    from server.services.nautilus_bridge.venues import (
        UnsupportedVenuePlan,
        freeze_native_venues,
    )

    try:
        native_venue_plan = freeze_native_venues(backtest, settings)
    except UnsupportedVenuePlan as exc:
        raise ValueError(str(exc)) from exc
    settings["venues"] = native_venue_plan["venues"]
    settings["strategy_venue_bindings"] = native_venue_plan["strategy_bindings"]
    settings["account_model"] = native_venue_plan["account_model"]
    settings["execution_model"] = native_venue_plan["execution_model"]
    settings["shared_market_data"] = native_venue_plan["shared_market_data"]

    from server.services.nautilus_bridge.config import (
        UnsupportedExecutionConfig,
        freeze_nautilus_venue_settings,
        freeze_instrument_execution_policy,
        parse_frozen_instrument_execution_policy,
    )

    raw_policy = settings.get("instrument_execution_policy")
    if raw_policy is not None:
        try:
            policy = parse_frozen_instrument_execution_policy(raw_policy)
        except UnsupportedExecutionConfig as exc:
            raise ValueError(str(exc)) from exc
        if policy.settlement_rule_set_ref is not None:
            raise ValueError(
                "settlement-rule references must come from the server's registered source adapter"
            )
    else:
        policy_input = settings.pop("instrument_execution_policy_overrides", {})
        if not isinstance(policy_input, Mapping):
            raise ValueError("instrument_execution_policy_overrides must be an object")
        if set(policy_input) - {
            "daily_settlement_scope_overrides", "daily_settlement_instrument_overrides",
            "cost_basis_scope_overrides", "cost_basis_instrument_overrides",
        }:
            raise ValueError("instrument_execution_policy_overrides contains unsupported fields")

        preset = str(settings.get("engine_mode") or "auto").strip().lower()
        accounting_mode = str(settings.get("accounting_mode") or "Auto").strip().lower()
        if preset == "custom":
            if accounting_mode == "basic":
                preset = "basic"
            elif accounting_mode == "auto":
                preset = "auto"
            elif accounting_mode not in {"custom", ""}:
                raise ValueError(f"unsupported accounting mode for NautilusTrader: {accounting_mode}")

        daily_value = settings.get("daily_mark_to_market_enabled")
        if isinstance(daily_value, str) and daily_value.strip().lower() in {"", "auto", "automatic"}:
            daily_value = None
        elif daily_value not in (None, ""):
            daily_value = _explicit_bool(daily_value, "daily_mark_to_market_enabled")
            daily_value = "eligible_products" if daily_value else "disabled"

        cost_basis_value = settings.get("cost_basis_method")
        if isinstance(cost_basis_value, str) and cost_basis_value.strip().lower() in {"", "auto", "automatic"}:
            cost_basis_value = None

        settlement_overrides = dict(
            policy_input.get("daily_settlement_scope_overrides") or {},
        )
        instrument_settlement_overrides = dict(
            policy_input.get("daily_settlement_instrument_overrides") or {},
        )
        basis_scope_overrides = dict(policy_input.get("cost_basis_scope_overrides") or {})
        basis_instrument_overrides = dict(
            policy_input.get("cost_basis_instrument_overrides") or {},
        )
        _collect_group_policy_overrides(
            backtest, settlement=settlement_overrides,
            cost_basis=basis_scope_overrides,
        )
        _collect_policy_fields_from_custom_products(
            settings.get("custom_product_fields") or [],
            settlement=instrument_settlement_overrides,
            cost_basis=basis_instrument_overrides,
        )
        if settings.get("settlement_rule_set_ref") not in (None, ""):
            raise ValueError(
                "settlement_rule_set_ref is server-owned and cannot be supplied by configuration"
            )
        try:
            policy = freeze_instrument_execution_policy(
                preset=preset,
                # No verified ruleset is currently registered. The policy
                # remains explicit, and the execution compiler blocks DMTM.
                settlement_rule_set_ref=None,
                daily_settlement_default=daily_value,
                daily_settlement_scope_overrides=settlement_overrides,
                daily_settlement_instrument_overrides=instrument_settlement_overrides,
                cost_basis_default=cost_basis_value,
                cost_basis_scope_overrides=basis_scope_overrides,
                cost_basis_instrument_overrides=basis_instrument_overrides,
            )
        except UnsupportedExecutionConfig as exc:
            raise ValueError(str(exc)) from exc

    policy_manifest = policy.manifest()
    policy_scope_refs = {
        ref
        for key in ("daily_settlement", "position_cost_basis")
        for ref in (policy_manifest[key].get("scope_overrides") or {})
    }
    if not policy_scope_refs.issubset(scopes):
        raise ValueError(
            "execution-policy product-group exceptions must refer to a selected frozen product group"
        )
    settings["instrument_execution_policy"] = policy_manifest

    from server.services.nautilus_bridge.run_spec import freeze_execution_contract

    execution["nautilus_contract"] = freeze_execution_contract(
        settings,
        product_scope_refs=list(scopes),
        native_venue_plan=native_venue_plan,
        instrument_execution_policy=policy_manifest,
    )

    # Presets and their UI knobs are intent, not the effective RunSpec
    # contract. Keep non-policy settings intact for the remaining compilers.
    for key in (
        "engine_mode", "accounting_mode", "daily_mark_to_market_enabled",
        "cost_basis_method", "settlement_rule_set_ref",
        "strategy_book_mode",
    ):
        settings.pop(key, None)
    custom_fields = settings.get("custom_product_fields")
    if isinstance(custom_fields, list):
        remaining = [
            item for item in custom_fields
            if not (isinstance(item, dict) and item.get("field") in {
                "DailyMarkToMarketEnabled", "CostBasisMethod",
            })
        ]
        if remaining:
            settings["custom_product_fields"] = remaining
        else:
            settings.pop("custom_product_fields", None)
    try:
        settings["nautilus_venue"] = freeze_nautilus_venue_settings(
            settings.get("nautilus_venue"),
        )
    except UnsupportedExecutionConfig as exc:
        raise ValueError(str(exc)) from exc
    return frozen


def _backtest_product_scope_refs(backtest: dict[str, Any]) -> tuple[str, ...]:
    refs: set[str] = set()

    def add(item: object) -> None:
        if not isinstance(item, dict):
            return
        nested = item.get("product_path_selection")
        if isinstance(nested, dict):
            for key in ("product_path_selection_id", "selection_id", "id"):
                value = str(nested.get(key) or "").strip()
                if value:
                    refs.add(value)
                    return
        for key in ("product_path_selection_id", "product_scope_ref", "product_group_ref"):
            value = str(item.get(key) or "").strip()
            if value:
                refs.add(value)
                return

    add(backtest)
    for collection in ("groups", "ls_configs", "configuration_groups"):
        for item in backtest.get(collection) or []:
            add(item)
    return tuple(sorted(refs))


def _collect_group_policy_overrides(
    backtest: dict[str, Any], *, settlement: dict[str, object],
    cost_basis: dict[str, object],
) -> None:
    for group in backtest.get("groups") or []:
        if not isinstance(group, dict):
            continue
        overrides = group.get("execution_policy_overrides")
        if not isinstance(overrides, dict):
            continue
        ref = _scope_ref(group)
        if not ref:
            raise ValueError("group execution-policy override requires a product-group reference")
        if "daily_settlement_enabled" in overrides:
            _set_unique_override(
                settlement, ref, overrides["daily_settlement_enabled"],
                "daily_settlement_scope_overrides",
            )
        if "position_cost_basis" in overrides:
            _set_unique_override(
                cost_basis, ref, overrides["position_cost_basis"],
                "cost_basis_scope_overrides",
            )
        if set(overrides) - {"daily_settlement_enabled", "position_cost_basis"}:
            raise ValueError(f"unsupported group execution-policy override for {ref}")


def _collect_policy_fields_from_custom_products(
    rows: object, *, settlement: dict[str, object], cost_basis: dict[str, object],
) -> None:
    if not isinstance(rows, list):
        raise ValueError("custom_product_fields must be a list")
    for row in rows:
        if not isinstance(row, dict):
            continue
        field = row.get("field")
        target = (
            settlement if field == "DailyMarkToMarketEnabled"
            else cost_basis if field == "CostBasisMethod"
            else None
        )
        if target is None:
            continue
        instrument = str(row.get("product") or row.get("instrument_id") or "").strip()
        if not instrument:
            raise ValueError(f"{field} override requires a product or instrument_id")
        if row.get("start") or row.get("end"):
            raise ValueError(f"{field} does not support dated overrides in this RunSpec contract")
        value = row.get("value")
        if field == "DailyMarkToMarketEnabled":
            value = _explicit_bool(value, field)
        _set_unique_override(target, instrument, value, field)


def _explicit_bool(value: object, field: str) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "on", "enabled"}:
        return True
    if text in {"0", "false", "no", "off", "disabled"}:
        return False
    raise ValueError(f"{field} requires an explicit boolean")


def _scope_ref(group: dict[str, Any]) -> str:
    nested = group.get("product_path_selection")
    if isinstance(nested, dict):
        for key in ("product_path_selection_id", "selection_id", "id"):
            value = str(nested.get(key) or "").strip()
            if value:
                return value
    for key in ("product_path_selection_id", "product_scope_ref", "product_group_ref"):
        value = str(group.get(key) or "").strip()
        if value:
            return value
    return ""


def _set_unique_override(
    target: dict[str, object], ref: str, value: object, field: str,
) -> None:
    if ref in target and target[ref] != value:
        raise ValueError(f"conflicting {field} overrides for {ref}")
    target[ref] = value

