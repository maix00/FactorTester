"""CounterParty — declarative fee/margin/liquidity commercial-terms presets.

Not a runtime object: registering a profile injects its field defaults into
the SAME `default_when` mechanism `EngineModule.engine_mode`'s basic/auto/
exact presets already use -- a `"counterparty_profile"` source_key alongside
the existing `"engine_mode"` one on each target field (`FeeModule.fee_mode`,
`MarginModule.margin_mode`, ...), so `strategy_config_builder.
_default_value_for_field` resolves it with zero new resolution passes and no
change to `resolve_group_settings`/`build_strategy_configs`. A strategy's
explicitly-set field value always wins over any `default_when` expansion --
that's `_default_value_for_field`'s existing behavior, not something this
module re-implements. See ADR-032.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from tools.testers.backtest.engines.native.fields import FieldRef


@dataclass(frozen=True)
class CounterPartyProfile:
    id: str
    label: str
    field_defaults: dict[FieldRef, Any] = field(default_factory=dict)


_COUNTERPARTY_PROFILES: dict[str, CounterPartyProfile] = {}


def register_counterparty_profile(profile: CounterPartyProfile) -> CounterPartyProfile:
    if not profile.id:
        raise ValueError("counterparty profile id is required")
    _COUNTERPARTY_PROFILES[profile.id] = profile
    return profile


def counterparty_profile(profile_id: object) -> CounterPartyProfile | None:
    return _COUNTERPARTY_PROFILES.get(str(profile_id))


def registered_counterparty_profiles() -> dict[str, CounterPartyProfile]:
    return dict(_COUNTERPARTY_PROFILES)


def unregister_counterparty_profile(profile_id: str) -> None:
    """Remove a profile and its injected `default_when` entries. Mainly for
    test isolation (this registry is process-global mutable state, same as
    `traderules`'s exchange-rule registries) -- production code registers
    profiles once at import time and never unregisters them."""
    profile = _COUNTERPARTY_PROFILES.pop(profile_id, None)
    if profile is None:
        return
    for ref in profile.field_defaults:
        _remove_default_when(ref, profile_id)
    _refresh_counterparty_profile_options()


def _remove_default_when(ref: FieldRef, profile_id: str) -> None:
    from tools.testers.backtest.modules.registry import _ALL_MODULE_CLASSES

    for cls in _ALL_MODULE_CLASSES:
        for field_name, fd in cls.fields.items():
            if getattr(cls, field_name, None) != ref:
                continue
            if fd.default_when is not None:
                fd.default_when.get("counterparty_profile", {}).pop(profile_id, None)
            return


def apply_counterparty_profile_defaults() -> None:
    """Inject every registered profile's field defaults into each target
    field's own `default_when["counterparty_profile"]` dict, and refresh
    `EngineModule.counterparty_profile`'s select options. Called once from
    `register_all_module_settings`, after all profiles have been registered
    by their source modules -- mirrors
    `refresh_custom_product_field_definitions`'s timing."""
    for profile in _COUNTERPARTY_PROFILES.values():
        for ref, value in profile.field_defaults.items():
            _inject_default_when(ref, profile.id, value)
    _refresh_counterparty_profile_options()


def _inject_default_when(ref: FieldRef, profile_id: str, value: Any) -> None:
    from tools.testers.backtest.modules.registry import _ALL_MODULE_CLASSES

    for cls in _ALL_MODULE_CLASSES:
        for field_name, fd in cls.fields.items():
            if getattr(cls, field_name, None) != ref:
                continue
            if fd.default_when is not None:
                fd.default_when.setdefault("counterparty_profile", {})[profile_id] = value
            else:
                cls.fields[field_name] = replace(
                    fd, default_when={"counterparty_profile": {profile_id: value}})
            return
    raise ValueError(f"counterparty profile field {ref.qualified_name!r} is not a registered field")


def _refresh_counterparty_profile_options() -> None:
    from tools.testers.backtest.modules.engine import EngineModule

    fd = EngineModule.fields["counterparty_profile"]
    EngineModule.fields["counterparty_profile"] = replace(
        fd,
        options=(("", "不使用预设"),) + tuple(
            (profile.id, profile.label) for profile in _COUNTERPARTY_PROFILES.values()
        ),
    )


def _register_default_counterparty_profiles() -> None:
    """Seed a single placeholder profile equivalent to engine_mode="auto"'s
    own defaults, expressed through the counterparty_profile channel instead
    -- proves the mechanism end to end without inventing a real broker's
    fee/margin numbers. Real named presets (e.g. a specific futures company's
    published markup) get registered here once there's a real source for
    them."""
    from tools.testers.backtest.modules.fee import FeeModule
    from tools.testers.backtest.modules.margin import MarginModule
    from tools.testers.backtest.modules.trading_rule import TradingRuleModule

    register_counterparty_profile(CounterPartyProfile(
        id="exchange_base",
        label="交易所基准（不加价）",
        field_defaults={
            FeeModule.fee_mode: "auto",
            MarginModule.margin_mode: "auto",
            TradingRuleModule.accounting_mode: "Auto",
            TradingRuleModule.use_int_position: True,
        },
    ))


_register_default_counterparty_profiles()
