from __future__ import annotations

import pytest

from tools.testers.backtest.modules.registry import _ALL_MODULE_CLASSES
from tools.testers.settings import backtest_setting_registry, resolve_group_settings


_APPLICATIONS = (
    "group_test",
    "ic_test",
    "factor_evaluation",
    "factor_type_analysis",
)


def _public_module_setting_keys() -> set[str]:
    return {
        key
        for module in _ALL_MODULE_CLASSES
        for key, field in getattr(module, "fields", {}).items()
        if field.public
    }


def _resolve(local_values: dict, group_values: dict | None = None) -> dict:
    application = backtest_setting_registry.get("group_test")
    return resolve_group_settings(
        application,
        local_values=local_values,
        group_values={"group-1": group_values or {}},
        group_ids=("group-1",),
    )["group-1"]


@pytest.mark.parametrize("application_name", _APPLICATIONS)
def test_registered_setting_projections_have_exact_keys(application_name: str) -> None:
    """A client must see the same closed setting set in every projection."""
    application = backtest_setting_registry.get(application_name)
    manifest = application.manifest()

    registered = set(application.settings)
    assert set(manifest["defaults"]) == registered
    assert set(manifest["field_contracts"]["settings"]) == registered
    assert all(
        manifest["defaults"][key]["module"]
        for key in registered
    )


def test_group_test_registers_every_public_executable_field_and_no_extra_field() -> None:
    """The module FieldDefinition set is the source of truth for group settings."""
    application = backtest_setting_registry.get("group_test")
    manual_settings = {
        "setting_template",
        "category_candidates",
        "category",
    }

    assert set(application.settings) == _public_module_setting_keys() | manual_settings


@pytest.mark.parametrize("application_name", _APPLICATIONS)
def test_condition_dependencies_are_registered_before_they_reach_clients(
    application_name: str,
) -> None:
    application = backtest_setting_registry.get(application_name)

    for setting in application.settings.values():
        dependencies = set(setting.visible_if)
        dependencies.update(setting.editable_if)
        dependencies.update(setting.default_if)
        assert dependencies <= set(application.settings), (
            f"{application_name}/{setting.key} references unregistered "
            f"settings: {sorted(dependencies - set(application.settings))}"
        )


def test_conditional_defaults_materialize_into_the_complete_resolved_settings_map() -> None:
    basic = _resolve({"engine": "native", "engine_mode": "basic"})
    assert {
        key: basic[key]
        for key in (
            "warmup_mode", "fee_mode", "transaction_fee_source",
            "margin_mode", "margin_call_mode", "accounting_mode",
            "historical_field_policy", "use_minor_units", "use_int_position",
        )
    } == {
        "warmup_mode": "none",
        "fee_mode": "zero",
        "transaction_fee_source": "auto",
        "margin_mode": "none",
        "margin_call_mode": "off",
        "accounting_mode": "Basic",
        "historical_field_policy": "auto",
        "use_minor_units": "false",
        "use_int_position": "false",
    }

    custom_exchange = _resolve({
        "engine": "native",
        "engine_mode": "custom",
        "counterparty_profile": "exchange_base",
    })
    assert {
        key: custom_exchange[key]
        for key in (
            "fee_mode", "transaction_fee_source", "margin_mode",
            "accounting_mode", "use_int_position",
        )
    } == {
        "fee_mode": "auto",
        "transaction_fee_source": "exchange",
        "margin_mode": "auto",
        "accounting_mode": "Auto",
        "use_int_position": "true",
    }


def test_editable_values_win_only_when_the_registered_condition_allows_them() -> None:
    custom = _resolve({
        "engine": "native",
        "engine_mode": "custom",
        "fee_mode": "fixed",
        "margin_mode": "fixed",
        "margin_call_mode": "warn",
        "accounting_mode": "Custom",
        "cost_basis_method": "FIFO",
        "historical_field_policy": "strict_historical",
        "use_minor_units": "false",
        "warmup_mode": "fixed",
    })
    assert {
        key: custom[key]
        for key in (
            "fee_mode", "margin_mode", "margin_call_mode", "accounting_mode",
            "cost_basis_method", "historical_field_policy", "use_minor_units",
            "warmup_mode",
        )
    } == {
        "fee_mode": "fixed",
        "margin_mode": "fixed",
        "margin_call_mode": "warn",
        "accounting_mode": "Custom",
        "cost_basis_method": "FIFO",
        "historical_field_policy": "strict_historical",
        "use_minor_units": "false",
        "warmup_mode": "fixed",
    }

    basic = _resolve({
        "engine": "native",
        "engine_mode": "basic",
        "fee_mode": "fixed",
        "transaction_fee_source": "openctp",
        "margin_mode": "fixed",
        "margin_call_mode": "liquidate",
        "accounting_mode": "Custom",
        "historical_field_policy": "strict_historical",
        "use_minor_units": "true",
        "warmup_mode": "fixed",
    })
    assert {
        key: basic[key]
        for key in (
            "fee_mode", "transaction_fee_source", "margin_mode",
            "margin_call_mode", "accounting_mode", "historical_field_policy",
            "use_minor_units", "warmup_mode",
        )
    } == {
        "fee_mode": "zero",
        "transaction_fee_source": "auto",
        "margin_mode": "none",
        "margin_call_mode": "off",
        "accounting_mode": "Basic",
        "historical_field_policy": "auto",
        "use_minor_units": "false",
        "warmup_mode": "fixed",
    }
    fallbacks = {
        item["setting_key"]: item
        for item in basic["_setting_fallbacks"]
        if item["reason"] == "non_editable_value_ignored"
    }
    assert set(fallbacks) >= {
        "fee_mode", "transaction_fee_source", "margin_mode",
        "margin_call_mode", "accounting_mode", "historical_field_policy",
        "use_minor_units",
    }


def test_custom_engine_rejects_unknown_fee_mode() -> None:
    with pytest.raises(ValueError, match="invalid value for fee_mode"):
        _resolve({
            "engine": "native",
            "engine_mode": "custom",
            "fee_mode": "none",
        })


def test_resolved_settings_have_no_missing_or_unregistered_keys() -> None:
    application = backtest_setting_registry.get("group_test")
    resolved = resolve_group_settings(
        application,
        local_values={"engine": "native", "engine_mode": "auto"},
        group_values={"group-1": {}},
        group_ids=("group-1",),
    )["group-1"]

    resolved_setting_keys = set(resolved) - {"_setting_fallbacks"}
    assert resolved_setting_keys == set(application.settings)
    if "_setting_fallbacks" in resolved:
        assert all(
            item["setting_key"] in application.settings
            for item in resolved["_setting_fallbacks"]
        )
