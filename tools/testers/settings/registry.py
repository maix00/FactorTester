"""Registry for backend-owned setting tabs and controls."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .contracts import (
    ChipDefinition,
    ResultTabDefinition,
    RunFieldDefinition,
    ScopePolicy,
    SettingDefinition,
    SettingModule,
    SettingsSurface,
    SettingTab,
    SurfaceFlow,
    TabMountPoint,
)


@dataclass(slots=True)
class ApplicationSettings:
    application: str
    modules: dict[str, SettingModule] = field(default_factory=dict)
    tabs: dict[str, SettingTab] = field(default_factory=dict)
    settings: dict[str, SettingDefinition] = field(default_factory=dict)
    chip_fields: dict[str, ChipDefinition] = field(default_factory=dict)
    result_tabs: dict[str, ResultTabDefinition] = field(default_factory=dict)
    run_fields: dict[str, RunFieldDefinition] = field(default_factory=dict)
    surfaces: dict[str, SettingsSurface] = field(default_factory=dict)
    flows: list[SurfaceFlow] = field(default_factory=list)
    manifest_extensions: dict[str, dict[str, Any]] = field(default_factory=dict)
    accepted_global_default_keys: tuple[str, ...] = ()

    def register_module(self, module: SettingModule) -> None:
        if module.key in self.modules:
            raise ValueError(f"duplicate setting module: {module.key}")
        self.modules[module.key] = module

    def register_tab(self, tab: SettingTab) -> None:
        if tab.key in self.tabs:
            raise ValueError(f"duplicate setting tab: {tab.key}")
        self.tabs[tab.key] = tab

    def register_setting(self, setting: SettingDefinition) -> None:
        if setting.key in self.settings:
            raise ValueError(f"duplicate setting: {setting.key}")
        self._ensure_tab_for_setting(setting)
        if setting.tab not in self.tabs:
            raise ValueError(f"setting {setting.key} references unknown tab {setting.tab}")
        if setting.module not in self.modules:
            raise ValueError(
                f"setting {setting.key} references unknown module {setting.module}"
            )
        self.settings[setting.key] = setting

    def _ensure_tab_for_setting(self, setting: SettingDefinition) -> None:
        if setting.tab in self.tabs:
            return
        self.tabs[setting.tab] = SettingTab(
            key=setting.tab,
            label=setting.tab_label or self._fallback_tab_label(setting),
            mount_points=self._mount_points_for_scope(setting.scope_policy),
            layout_template=setting.tab_layout_template or "settings-grid",
            order=setting.tab_order if setting.tab_order is not None else self._next_tab_order(setting),
            default_mount_points=setting.tab_default_mount_points,
            summary_template=setting.tab_summary_template,
            summary_keys=setting.tab_summary_keys,
            content_adapter=setting.tab_content_adapter,
            content_options=dict(setting.tab_content_options),
        )

    def _fallback_tab_label(self, setting: SettingDefinition) -> str:
        module = self.modules.get(setting.module)
        if module is not None and module.key == setting.tab:
            return module.label
        return setting.tab.replace("_", " ").title()

    def _mount_points_for_scope(self, scope: ScopePolicy) -> tuple[TabMountPoint, ...]:
        return (TabMountPoint.LOCAL_SETTINGS, TabMountPoint.GROUP_SETTINGS)

    def _next_tab_order(self, setting: SettingDefinition) -> int:
        module = self.modules.get(setting.module)
        if module is not None:
            return module.order
        return (len(self.tabs) + 1) * 10

    def register_chip_field(self, chip: ChipDefinition) -> None:
        if chip.key in self.chip_fields:
            raise ValueError(f"duplicate chip field: {chip.key}")
        if chip.module not in self.modules:
            raise ValueError(
                f"chip {chip.key} references unknown module {chip.module}"
            )
        self.chip_fields[chip.key] = chip

    def register_result_tab(self, tab: ResultTabDefinition) -> None:
        if tab.key in self.result_tabs:
            raise ValueError(f"duplicate result tab: {tab.key}")
        if tab.module not in self.modules:
            raise ValueError(
                f"result tab {tab.key} references unknown module {tab.module}"
            )
        self.result_tabs[tab.key] = tab

    def register_run_field(self, run_field: RunFieldDefinition) -> None:
        if run_field.key in self.run_fields:
            raise ValueError(f"duplicate run field: {run_field.key}")
        self.run_fields[run_field.key] = run_field

    def register_surface(self, surface: SettingsSurface) -> None:
        if surface.key in self.surfaces:
            raise ValueError(f"duplicate settings surface: {surface.key}")
        self.surfaces[surface.key] = surface

    def register_flow(self, flow: SurfaceFlow) -> None:
        if flow.surface not in self.surfaces:
            raise ValueError(f"flow {flow.key} references unknown surface {flow.surface}")
        if any(f.surface == flow.surface and f.key == flow.key for f in self.flows):
            raise ValueError(f"duplicate flow {flow.key} on surface {flow.surface}")
        self.flows.append(flow)

    def register_accepted_global_default_keys(self, *keys: str) -> None:
        ordered = list(self.accepted_global_default_keys)
        for key in keys:
            if key and key not in ordered:
                ordered.append(key)
        self.accepted_global_default_keys = tuple(ordered)

    def register_manifest_extension(self, key: str, manifest: dict[str, Any]) -> None:
        """Attach one domain-owned manifest without teaching this registry its schema."""
        if not key or key in self.manifest_extensions:
            raise ValueError(f"duplicate or empty manifest extension: {key}")
        if not isinstance(manifest, dict) or not manifest:
            raise ValueError(f"manifest extension {key} must be a non-empty object")
        self.manifest_extensions[key] = dict(manifest)

    def manifest(self) -> dict[str, Any]:
        ordered_tabs = sorted(self.tabs.values(), key=lambda item: item.order)
        ordered_modules = sorted(self.modules.values(), key=lambda item: item.order)
        manifest = {
            "schema_version": 1,
            "application": self.application,
            "modules": [module.to_dict() for module in ordered_modules],
            "tab_lists": {
                mount.value: [
                    tab.to_dict() for tab in ordered_tabs if mount in tab.mount_points
                ]
                for mount in TabMountPoint
            },
            "default_mounted_tabs": {
                mount.value: [
                    tab.key for tab in ordered_tabs
                    if mount in tab.default_mount_points
                ]
                for mount in TabMountPoint
            },
            "defaults": {
                key: {
                    "order": index,
                    "value": setting.default,
                    "label": setting.label,
                    "control_template": setting.control_template,
                    "tab_key": setting.tab,
                    "scope_policy": setting.scope_policy.value,
                    "module": setting.module,
                    "chip_template": setting.chip_template,
                    "adapter_managed": setting.adapter_managed,
                    "show_chip": setting.show_chip,
                    "execution_policy": setting.execution_policy,
                    "info_overlay": setting.info_overlay,
                    "has_instance": setting.instance_class is not None,
                    "minimum": setting.minimum,
                    "maximum": setting.maximum,
                    "step": setting.step,
                    "help_text": setting.help_text,
                    "engine_defaults": dict(setting.engine_defaults),
                    "serialization": dict(setting.serialization),
                    "visible_when": {
                        key: list(values)
                        for key, values in setting.visible_when.items()
                    },
                    "editable_when": {
                        key: list(values)
                        for key, values in setting.editable_when.items()
                    },
                    "default_when": {
                        key: dict(values)
                        for key, values in setting.default_when.items()
                    },
                    "disabled_values_by_engine": {
                        engine: list(values)
                        for engine, values in setting.disabled_values_by_engine.items()
                    },
                    "options": [
                        {"value": option.value, "label": option.label}
                        for option in setting.options
                    ],
                }
                for index, (key, setting) in enumerate(self.settings.items(), start=1)
            },
            "chip_fields": [
                chip.to_dict()
                for chip in sorted(self.chip_fields.values(), key=lambda item: item.order)
            ],
            "result_tabs": [
                tab.to_dict()
                for tab in sorted(self.result_tabs.values(), key=lambda item: item.order)
            ],
            "run_fields": [
                run_field.to_dict()
                for run_field in sorted(self.run_fields.values(), key=lambda item: item.order)
            ],
            "surfaces": [
                surface.to_dict()
                for surface in sorted(self.surfaces.values(), key=lambda item: item.order)
            ],
            "flows": [
                flow.to_dict()
                for flow in sorted(self.flows, key=lambda item: (item.surface, item.order, item.key))
            ],
            "accepted_global_default_keys": list(self.accepted_global_default_keys),
            "tab_url_template": f"/api/backtest/settings/{self.application}/tabs/{{tab_key}}",
        }
        collisions = set(manifest) & set(self.manifest_extensions)
        if collisions:
            raise ValueError(f"manifest extensions collide with built-in fields: {collisions}")
        manifest.update(self.manifest_extensions)
        return manifest

    def tab_manifest(self, tab_key: str) -> dict[str, Any]:
        try:
            tab = self.tabs[tab_key]
        except KeyError as exc:
            raise KeyError(f"unknown setting tab: {tab_key}") from exc
        return {
            "schema_version": 1,
            "application": self.application,
            "tab": tab.to_dict(),
            "settings": [
                setting.to_dict()
                for setting in self.settings.values()
                if setting.tab == tab_key
            ],
        }


class BacktestSettingRegistry:
    def __init__(self) -> None:
        self._applications: dict[str, ApplicationSettings] = {}

    def register(self, application: ApplicationSettings) -> None:
        if application.application in self._applications:
            raise ValueError(f"duplicate backtest application: {application.application}")
        self._applications[application.application] = application

    def get(self, application: str) -> ApplicationSettings:
        try:
            return self._applications[application]
        except KeyError as exc:
            raise KeyError(f"unknown backtest application: {application}") from exc

    def shared_global_default_keys(self, applications: tuple[str, ...]) -> list[str]:
        counts: dict[str, int] = {}
        ordered: list[str] = []
        for application in applications:
            app = self.get(application)
            for key in app.accepted_global_default_keys:
                if key not in ordered:
                    ordered.append(key)
                counts[key] = counts.get(key, 0) + 1
        return [key for key in ordered if counts.get(key, 0) >= 2]
