"""Module registry base — no backtest/settings/strategy coupling.

Purpose:
  - Collect ExecutableModule subclasses.
  - Provide instantiate(*keys) / instantiate_all().
  - Produce a module_manifest() for frontends.

This lives under tools.data.modules so that IC-test, factor-evaluation, and
any other test domain can inherit from it without dragging in backtest-specific
dependencies (ApplicationSettings, strategy parsing, etc.).
"""

from __future__ import annotations

from typing import Any


class ModuleRegistry:
    """Base registry for executable modules.

    Subclasses register their own module classes and may add domain-specific
    logic (settings schema, strategy parsing, etc.).

    The only contract: every registered class must expose `key`, `label`,
    `order` (int), and `phases` (an iterable of objects with phase/order/
    before/after/needs/produces/records attributes).
    """

    # Subclasses should set this to a unique application key
    application: str = ""

    # Override in subclass: tuple of module classes
    _module_classes: tuple[type[Any], ...] = ()

    def __init__(self) -> None:
        self._by_key: dict[str, type[Any]] = {}
        for cls in self.__class__._module_classes:
            key: str = getattr(cls, "key", "")
            if not key:
                raise TypeError(
                    f"{cls.__name__} must define a non-empty `key`"
                )
            if key in self._by_key:
                raise ValueError(f"duplicate module key: {key}")
            self._by_key[key] = cls

    # ── module discovery ───────────────────────────────────────

    @property
    def module_keys(self) -> tuple[str, ...]:
        return tuple(self._by_key.keys())

    def get_module_class(self, key: str) -> type[Any]:
        try:
            return self._by_key[key]
        except KeyError:
            raise KeyError(f"unknown module: {key!r}") from None

    def instantiate_all(self) -> list[Any]:
        return [cls() for cls in self._by_key.values()]

    def instantiate(self, *keys: str) -> list[Any]:
        return [self.get_module_class(key)() for key in keys]

    # ── manifest ───────────────────────────────────────────────

    def module_manifest(self) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for cls in sorted(self._by_key.values(), key=lambda c: getattr(c, "order", 0)):
            phases = []
            for ph in getattr(cls, "phases", ()):
                phases.append({
                    "phase": getattr(ph, "phase", ""),
                    "order": getattr(ph, "order", 0),
                    "before": list(getattr(ph, "before", ())),
                    "after": list(getattr(ph, "after", ())),
                    "needs": list(getattr(ph, "needs", ())),
                    "produces": list(getattr(ph, "produces", ())),
                    "records": list(getattr(ph, "records", ())),
                })
            entries.append({
                "key": getattr(cls, "key", ""),
                "label": getattr(cls, "label", ""),
                "order": getattr(cls, "order", 0),
                "phases": phases,
                "output_fields": list(getattr(cls, "output_fields", ())),
            })
            result_metric_manifest = getattr(cls, "result_metric_manifest", None)
            if callable(result_metric_manifest):
                entries[-1]["result_metrics"] = list(result_metric_manifest())
        return entries

    # ── output collection ───────────────────────────────────────

    def collect_outputs(
        self,
        group_result: Any,
        owner: dict[str, Any],
        settings: dict[str, Any],
    ) -> dict[str, Any]:
        """Collect frontend output fields from all registered modules.

        Each module may declare `output_fields` and a `collect_outputs`
        classmethod. This method iterates all registered modules, calls
        each classmethod, and merges the results into a single dict.

        Returns dict mapping field_name → value for serialization.
        """
        merged: dict[str, Any] = {}
        for key, cls in self._by_key.items():
            collector = getattr(cls, "collect_outputs", None)
            if collector is None:
                continue
            fields = collector(group_result=group_result, owner=owner, settings=settings)
            if fields:
                merged.update(fields)
        return merged

    # ── _FactorGroupTestGroup construction ─────────────────────

    def build_group_params(
        self,
        group_settings: dict[str, Any],
        raw_group: dict[str, Any],
    ) -> dict[str, Any]:
        """Collect _FactorGroupTestGroup construction params from all modules.

        Each module declares `group_params` (tuple of parameter names) and
        `build_group_params(group_settings, raw_group) -> dict`.

        Returns merged dict of all module-contributed params.
        """
        merged: dict[str, Any] = {}
        for key, cls in self._by_key.items():
            builder = getattr(cls, "build_group_params", None)
            if builder is None:
                continue
            params = builder(group_settings=group_settings, raw_group=raw_group)
            if params:
                merged.update(params)
        return merged

    # ── Progress manifest ─────────────────────────────────────

    def build_progress_manifest(self) -> list[dict[str, Any]]:
        """Build the full progress bar phase manifest from all modules.

        Each module declares `progress_phases`: tuple of {key, label, sub_steps?}.
        Duplicate keys are merged (sub_steps unioned).

        Returns the list in module registration order (sorted by order).
        """
        seen: dict[str, dict[str, Any]] = {}
        for key, cls in sorted(self._by_key.items(), key=lambda kv: getattr(kv[1], "order", 0)):
            for phase in getattr(cls, "progress_phases", ()):
                phase_key = str(phase.get("key", ""))
                if not phase_key:
                    continue
                if phase_key in seen:
                    # Merge sub_steps
                    existing_sub = seen[phase_key].get("sub_steps") or {}
                    new_sub = phase.get("sub_steps") or {}
                    if new_sub:
                        seen[phase_key]["sub_steps"] = {**existing_sub, **new_sub}
                else:
                    seen[phase_key] = {
                        "key": phase_key,
                        "label": str(phase.get("label", phase_key)),
                    }
                    sub = phase.get("sub_steps")
                    if sub:
                        seen[phase_key]["sub_steps"] = dict(sub)
        return list(seen.values())
