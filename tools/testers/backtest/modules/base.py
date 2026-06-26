"""Executable setting module base class and phase-method protocol.

Each module subclass:
  - Declares `key`, `label`, `order`, `phases` as class variables.
  - Overrides `on_<phase>(ctx)` methods for behaviour.
  - Reads its own setting values via `self.setting(key, default)`.

The runner discovers modules through the ApplicationSettings registry
and dispatches purely by phase name — it never imports a module by its
concrete class.
"""

from __future__ import annotations

from typing import Any, ClassVar

from tools.testers.backtest.engines.native.stages import PhaseContext, PhaseHandler


class ExecutableModule:
    """Base for all executable setting modules.

    Lifecycle:
      1. Runner instantiates the module.
      2. `bind_settings(values)` — called once before the run.
      3. `on_<phase>(ctx)` — called in topological order within each phase,
         once per market slice.

    The runner knows nothing about the module beyond this protocol.
    """

    key: ClassVar[str] = ""
    label: ClassVar[str] = ""
    order: ClassVar[int] = 100
    phases: ClassVar[tuple[PhaseHandler, ...]] = ()

    # ── Output fields for frontend serialization ──────────────────
    # output_fields: tuple of field names this module contributes to the
    #   serialized group output (e.g. "fee_costs", "trade_notional_ratios").
    # collect_outputs: classmethod that returns {field_name: value} given
    #   the post-run artifacts. Called by ModuleRegistry.collect_outputs().
    output_fields: ClassVar[tuple[str, ...]] = ()

    @classmethod
    def collect_outputs(
        cls,
        group_result: Any,
        owner: dict[str, Any],
        settings: dict[str, Any],
    ) -> dict[str, Any]:
        """Return {field_name: value} for this module's frontend output."""
        return {}

    # ── _FactorGroupTestGroup construction params ──────────────────
    # group_params: tuple of parameter names this module contributes when
    #   building a _FactorGroupTestGroup (e.g. "fee_mode", "fee_rate").
    # build_group_params: classmethod that returns {param: value} from settings.
    #   Called by ModuleRegistry.build_group_params() to eliminate hardcoding.
    group_params: ClassVar[tuple[str, ...]] = ()

    @classmethod
    def build_group_params(cls, group_settings: dict[str, Any], raw_group: dict[str, Any]) -> dict[str, Any]:
        """Return {param: value} for _FactorGroupTestGroup from settings/payload."""
        return {}

    # ── Progress phases ──────────────────────────────────────────
    # progress_phases: tuple of phase dicts this module contributes to the
    #   progress bar manifest. Each dict has:
    #     key: str          — unique phase key (e.g. "framework_execution")
    #     label: str        — display label
    #     sub_steps: dict   — optional {sub_key: sub_label, ...}
    #   Used by ModuleRegistry.build_progress_manifest() to produce the
    #   full GROUP_TEST_PHASES, replacing the hand-written metadata.py list.
    progress_phases: ClassVar[tuple[dict[str, Any], ...]] = ()

    # ── Setting definitions ──────────────────────────────────────
    # setting_definitions: tuple of dicts, each describing a SettingDefinition
    #   that this module owns. Keys mirror SettingDefinition constructor params.
    #   Registered by BacktestModuleRegistry.register_all_settings().
    #   Example:
    #     setting_definitions = (
    #         {"key": "fee_mode", "label": "费用规则", "tab": "cost",
    #          "control_template": "select", "default": "market",
    #          "scope_policy": "group_override",
    #          "options": (("none","无费用"), ("market","市场历史费率"), ("custom","自定义费率")),
    #          "chip_template": "费用: {value}"},
    #     )
    setting_definitions: ClassVar[tuple[dict[str, Any], ...]] = ()

    def __init__(self) -> None:
        self._settings: dict[str, Any] = {}

    def bind_settings(self, values: dict[str, Any]) -> None:
        """Called by the runner with this module's setting key→value pairs."""
        self._settings = dict(values)

    def setting(self, key: str, default: Any = None) -> Any:
        """Read a setting value for this module."""
        return self._settings.get(key, default)

    # ── Phase handlers (override in subclasses) ──────────────────

    def on_pre_replay(self, ctx: PhaseContext) -> None:
        pass

    def on_target_generation(self, ctx: PhaseContext) -> None:
        pass

    def on_risk(self, ctx: PhaseContext) -> None:
        pass

    def on_order_sizing(self, ctx: PhaseContext) -> None:
        pass

    def on_order_execution(self, ctx: PhaseContext) -> None:
        pass

    def on_order_matching(self, ctx: PhaseContext) -> None:
        pass

    def on_order_fill_accounting(self, ctx: PhaseContext) -> None:
        pass

    def on_accounting(self, ctx: PhaseContext) -> None:
        pass

    def on_report(self, ctx: PhaseContext) -> None:
        pass

    def on_post_replay(self, ctx: PhaseContext) -> None:
        pass
