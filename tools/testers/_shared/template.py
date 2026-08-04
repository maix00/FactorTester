"""Shared test-template setting declaration for executable test pages."""

from __future__ import annotations

from tools.testers.settings.contracts import (
    ScopePolicy,
    SettingDefinition,
    SettingModule,
    SettingTab,
    TabMountPoint,
)
from tools.testers.settings.registry import ApplicationSettings


def register_test_template_base(app: ApplicationSettings) -> None:
    """Declare the per-test template panel in the backend manifest."""
    if "test_template" not in app.modules:
        app.register_module(SettingModule(
            "test_template", "测试模板", "page", 1,
        ))
    if "test_template" not in app.tabs:
        app.register_tab(SettingTab(
            "test_template",
            "测试模板",
            (TabMountPoint.LOCAL_SETTINGS,),
            "custom",
            1,
            (TabMountPoint.LOCAL_SETTINGS,),
        ))
    if "setting_template" not in app.settings:
        app.register_setting(SettingDefinition(
            "setting_template",
            "测试模板",
            "test_template",
            "custom",
            None,
            ScopePolicy.LOCAL_ONLY,
            module="test_template",
            chip_template="模板: {value}",
            serialization={
                "kind": "setting_template",
                "template_scope": app.application,
            },
        ))
