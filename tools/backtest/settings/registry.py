"""Registry for backend-owned setting tabs and controls."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .contracts import (
    ChipDefinition,
    ResultTabDefinition,
    SettingDefinition,
    SettingModule,
    SettingTab,
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
        if setting.tab not in self.tabs:
            raise ValueError(f"setting {setting.key} references unknown tab {setting.tab}")
        if setting.module not in self.modules:
            raise ValueError(
                f"setting {setting.key} references unknown module {setting.module}"
            )
        self.settings[setting.key] = setting

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

    def register_accepted_global_default_keys(self, *keys: str) -> None:
        ordered = list(self.accepted_global_default_keys)
        for key in keys:
            if key and key not in ordered:
                ordered.append(key)
        self.accepted_global_default_keys = tuple(ordered)

    def manifest(self) -> dict[str, Any]:
        ordered_tabs = sorted(self.tabs.values(), key=lambda item: item.order)
        ordered_modules = sorted(self.modules.values(), key=lambda item: item.order)
        return {
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
                    "value": setting.default,
                    "label": setting.label,
                    "control_template": setting.control_template,
                    "tab_key": setting.tab,
                    "scope_policy": setting.scope_policy.value,
                    "module": setting.module,
                    "chip_template": setting.chip_template,
                    "engine_defaults": dict(setting.engine_defaults),
                    "serialization": dict(setting.serialization),
                    "visible_when": {
                        key: list(values)
                        for key, values in setting.visible_when.items()
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
                for key, setting in self.settings.items()
            },
            "chip_fields": [
                chip.to_dict()
                for chip in sorted(self.chip_fields.values(), key=lambda item: item.order)
            ],
            "result_tabs": [
                tab.to_dict()
                for tab in sorted(self.result_tabs.values(), key=lambda item: item.order)
            ],
            "accepted_global_default_keys": list(self.accepted_global_default_keys),
            "tab_url_template": f"/api/backtest/settings/{self.application}/tabs/{{tab_key}}",
        }

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
