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

from ..event_driven.stages import PhaseContext, PhaseHandler


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
