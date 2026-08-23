from __future__ import annotations

from tools.testers.settings.runtime_intent import (
    normalize_backtest_runtime_setting_intent,
)


def _payload(local_settings: dict, *, group: dict | None = None) -> dict:
    return {
        "schema_version": 1,
        "shared": {"factors": []},
        "ui": {},
        "analyses": {
            "backtest": {
                "local_settings": dict(local_settings),
                "groups": [group or {"id": "group-1", "splitCount": 5}],
                "ls_configs": [],
            },
        },
    }


def test_old_runtime_display_defaults_are_normalized_to_neutral_intent() -> None:
    payload = _payload({
        "engine": "native",
        "engine_mode": "auto",
        "cost_basis_method": "WeightAverage",
        "daily_mark_to_market_enabled": False,
        "use_int_position": False,
        "historical_field_policy": "latest_available",
        "use_minor_units": True,
        "transaction_fee_source": "exchange",
    })

    normalized, changes = normalize_backtest_runtime_setting_intent(payload)

    assert normalized["analyses"]["backtest"]["local_settings"] == {
        "engine": "native",
        "engine_mode": "auto",
        "cost_basis_method": "auto",
        "daily_mark_to_market_enabled": "auto",
        "use_int_position": "auto",
        "historical_field_policy": "auto",
        "use_minor_units": "auto",
        "transaction_fee_source": "auto",
    }
    assert {item["setting_key"] for item in changes} == {
        "cost_basis_method",
        "daily_mark_to_market_enabled",
        "use_int_position",
        "historical_field_policy",
        "use_minor_units",
        "transaction_fee_source",
    }
    assert payload["analyses"]["backtest"]["local_settings"][
        "daily_mark_to_market_enabled"
    ] is False


def test_custom_runtime_values_are_not_normalized() -> None:
    payload = _payload({
        "engine": "native",
        "engine_mode": "custom",
        "accounting_mode": "Custom",
        "cost_basis_method": "FIFO",
        "daily_mark_to_market_enabled": "true",
        "use_int_position": "false",
        "historical_field_policy": "strict_historical",
        "use_minor_units": "false",
        "transaction_fee_source": "exchange",
    })

    normalized, changes = normalize_backtest_runtime_setting_intent(payload)

    assert normalized == payload
    assert changes == []


def test_ignored_local_only_group_override_is_removed() -> None:
    payload = _payload(
        {"engine": "native", "engine_mode": "auto"},
        group={
            "id": "group-1",
            "splitCount": 5,
            "engine": "backtrader",
        },
    )

    normalized, changes = normalize_backtest_runtime_setting_intent(payload)

    assert "engine" not in normalized["analyses"]["backtest"]["groups"][0]
    assert changes == [{
        "scope": "group",
        "group_id": "group-1",
        "setting_key": "engine",
        "requested_value": "backtrader",
        "applied_value": None,
        "reason": "remove_ignored_local_only_override",
    }]
