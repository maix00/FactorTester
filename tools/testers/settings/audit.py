"""Audits for backend-owned tester tabs and field renderer contracts."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .registry import ApplicationSettings


# These are the editors currently materialized by the shared Web settings
# renderer.  The Web manifest tests compare this set with the JavaScript
# renderer's exported support check.
WEB_SETTING_EDITORS = frozenset({
    "input", "boolean", "json", "catalog", "select", "date", "time",
    "service_port", "profile", "server_picker", "runtime_bundle_picker",
    "output_picker", "custom_product_overrides", "factor_role_bindings",
    "ic_decay_grid", "ic_delay_grid", "ic_horizon_grid",
})

WEB_TAB_CONTENT_ADAPTERS = frozenset({
    "settings", "test_templates", "factor_selection", "product_path_selection",
    "category_selection", "run_inputs",
})

WEB_SURFACE_CONTENT_ADAPTERS = frozenset({
    "settings", "backtest_groups", "backtest_long_short",
    "backtest_custom_strategies", "ic_configuration_groups",
})


def audit_application_mounts(
    application: "ApplicationSettings", *, client: str = "web",
) -> list[str]:
    """Audit every registered field reachable from every mounted tab.

    This is intentionally a registry-level contract rather than a test of
    whichever tab happened to be opened in a browser. A field can be
    lazy-mounted, adapter-managed, or only present on Swift, so each manifest
    projection is checked independently before it reaches a client.
    """
    manifest = application.manifest(client=client)
    errors: list[str] = []
    defaults = manifest.get("defaults", {})
    contracts = manifest.get("field_contracts", {}).get("settings", {})
    if set(defaults) != set(contracts):
        errors.append(
            f"{application.application}: settings and field_contracts.settings differ"
        )

    for mount, mount_tabs in manifest.get("tab_lists", {}).items():
        seen_tabs: set[str] = set()
        for tab in mount_tabs:
            tab_key = str(tab.get("key") or "")
            if not tab_key:
                errors.append(f"{application.application}/{mount}: tab has no key")
                continue
            if tab_key in seen_tabs:
                errors.append(
                    f"{application.application}/{mount}: duplicate tab {tab_key}"
                )
            seen_tabs.add(tab_key)
            adapter = str(tab.get("content_adapter") or "settings")
            if adapter not in WEB_TAB_CONTENT_ADAPTERS:
                errors.append(
                    f"{application.application}/{mount}/{tab_key}: "
                    f"unknown content adapter {adapter}"
                )
            field_keys = [
                key for key, field in defaults.items()
                if field.get("tab_key") == tab_key
            ]
            tab_settings = {
                str(item.get("key") or "")
                for item in application.tab_manifest(tab_key).get("settings", [])
            }
            if set(field_keys) != tab_settings:
                errors.append(
                    f"{application.application}/{mount}/{tab_key}: "
                    "tab field list differs"
                )
            for key in field_keys:
                _audit_field(
                    errors, application.application, mount, tab_key, key, defaults[key], adapter,
                )

    for mount, mounted in manifest.get("default_mounted_tabs", {}).items():
        declared = {
            tab["key"] for tab in manifest.get("tab_lists", {}).get(mount, [])
        }
        for tab_key in mounted:
            if tab_key not in declared:
                errors.append(
                    f"{application.application}/{mount}: default tab {tab_key} is not mounted"
                )

    run_fields = manifest.get("run_fields", [])
    run_contracts = manifest.get("field_contracts", {}).get("run", {})
    if {item.get("key") for item in run_fields} != set(run_contracts):
        errors.append(
            f"{application.application}: run_fields and field_contracts.run differ"
        )
    for field in run_fields:
        key = str(field.get("key") or "")
        editor = str(field.get("value_descriptor", {}).get("editor") or "")
        if editor not in WEB_SETTING_EDITORS:
            errors.append(
                f"{application.application}/run/{key}: unsupported editor {editor}"
            )

    for surface in manifest.get("surfaces", []):
        adapter = str(surface.get("content_adapter") or "settings")
        if adapter not in WEB_SURFACE_CONTENT_ADAPTERS:
            errors.append(
                f"{application.application}/surface/{surface.get('key')}: "
                f"unknown content adapter {adapter}"
            )
    return errors


def _audit_field(
    errors: list[str], application: str, mount: str, tab_key: str,
    key: str, field: dict[str, Any], adapter: str,
) -> None:
    descriptor = field.get("value_descriptor") or {}
    editor = str(descriptor.get("editor") or "")
    prefix = f"{application}/{mount}/{tab_key}/{key}"
    if editor not in WEB_SETTING_EDITORS:
        errors.append(f"{prefix}: unsupported editor {editor}")
    if field.get("adapter_managed") and adapter == "settings":
        errors.append(f"{prefix}: adapter-managed field has no content adapter")
    if editor == "catalog" and not descriptor.get("option_source"):
        errors.append(f"{prefix}: catalog field has no option source")
    if (
        editor == "select"
        and descriptor.get("option_source") == "manifest.options"
        and not descriptor.get("options")
    ):
        errors.append(f"{prefix}: select field has no registered options")
    if descriptor.get("cardinality") == "many" and not (
        descriptor.get("item_type")
        or descriptor.get("value_type") in {"array", "grid", "output_request"}
    ):
        errors.append(f"{prefix}: multi-value field has no item type")
