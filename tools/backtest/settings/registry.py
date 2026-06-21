"""Registry for backend-owned setting tabs and controls."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .contracts import SettingDefinition, SettingTab, TabMountPoint


@dataclass(slots=True)
class ApplicationSettings:
    application: str
    tabs: dict[str, SettingTab] = field(default_factory=dict)
    settings: dict[str, SettingDefinition] = field(default_factory=dict)

    def register_tab(self, tab: SettingTab) -> None:
        if tab.key in self.tabs:
            raise ValueError(f"duplicate setting tab: {tab.key}")
        self.tabs[tab.key] = tab

    def register_setting(self, setting: SettingDefinition) -> None:
        if setting.key in self.settings:
            raise ValueError(f"duplicate setting: {setting.key}")
        if setting.tab not in self.tabs:
            raise ValueError(f"setting {setting.key} references unknown tab {setting.tab}")
        self.settings[setting.key] = setting

    def manifest(self) -> dict[str, Any]:
        ordered_tabs = sorted(self.tabs.values(), key=lambda item: item.order)
        return {
            "schema_version": 1,
            "application": self.application,
            "tab_lists": {
                mount.value: [
                    tab.to_dict() for tab in ordered_tabs if mount in tab.mount_points
                ]
                for mount in TabMountPoint
            },
            "defaults": {
                key: {
                    "value": setting.default,
                    "tab_key": setting.tab,
                    "scope_policy": setting.scope_policy.value,
                }
                for key, setting in self.settings.items()
            },
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
