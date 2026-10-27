"""Read-only JSON Schema projection of the canonical authoring registry.

This does not freeze a RunSpec or replace domain validation. Optional fields
stay absent until the author adds them; defaults are suggestions, not writes.
"""
from copy import deepcopy
from typing import Any

from tools.testers.configuration_schema import RESEARCH_CONFIGURATION_SCHEMA_VERSION


def _field_schema(setting: Any, *, english: bool) -> dict[str, Any]:
    descriptor = setting.value_descriptor.to_dict()
    kind = descriptor["value_type"]
    types = {"boolean": "boolean", "integer": "integer", "number": "number",
             "object": "object", "array": "array", "grid": "array",
             "output_request": "array"}
    value: dict[str, Any] = deepcopy(descriptor.get("schema") or {})
    if not value:
        if kind == "reference":
            value = {"anyOf": [{"type": "string"}, {"type": "object"}]}
        else:
            value = {"type": types.get(kind, "string")}
        if value.get("type") == "array":
            value["items"] = {}
        elif descriptor.get("cardinality") == "many":
            value = {"type": "array", "items": value}
    options = list(setting.options) or descriptor.get("options") or []
    if options:
        values = [{"const": option["value"], "title": option["value"] if english else option["label"]}
                  if isinstance(option, dict) else
                  {"const": option.value, "title": option.value if english else option.label}
                  for option in options]
        if setting.default is not None and not any(item["const"] == setting.default for item in values):
            values.append({"const": deepcopy(setting.default), "title": "Default" if english else "默认"})
        value = {"oneOf": values}
    for key in ("minimum", "maximum"):
        bound = descriptor.get(key)
        if bound is not None and value.get("type") in {"integer", "number"}:
            value[key] = bound
    default = deepcopy(setting.default)
    # "auto", empty string and null can be real registered inheritance modes.
    # Never coerce them into numeric zero or silently substitute a default.
    expected = value.get("type")
    if default is None:
        value = {"anyOf": [value, {"type": "null"}]}
    elif expected in {"number", "integer", "array", "object"} and isinstance(default, str):
        value = {"anyOf": [value, {"const": default}]}
    value.update({"title": setting.key if english else setting.label,
                  "default": default, "x-setting-key": setting.key,
                  "x-setting-rules": setting.field_spec().setting.rules.to_dict()})
    if setting.help_text and not english:
        value["description"] = setting.help_text
    return value


def configuration_editor_contract(*, locale: str = "zh") -> dict[str, Any]:
    from .applications import backtest_setting_registry

    english = locale.startswith("en")
    applications = {"backtest": "group_test", "ic": "ic_test",
                    "factor_evaluation": "factor_evaluation",
                    "factor_type_analysis": "factor_type_analysis"}
    analyses: dict[str, Any] = {}
    catalog = []
    for kind, application in applications.items():
        app = backtest_setting_registry.get(application)
        properties = {}
        for key, setting in app.settings.items():
            if setting.execution_policy != "include" or setting.adapter_managed:
                continue
            properties[key] = _field_schema(setting, english=english)
            catalog.append({"path": ["analyses", kind, "execution", "settings", key],
                            "key": key, "analysis": kind, "group": setting.tab,
                            "title": properties[key]["title"],
                            "description": properties[key].get("description", ""),
                            "value": deepcopy(setting.default)})
        analyses[kind] = {"type": "object", "title": kind,
                          "properties": {"execution": {"type": "object", "properties": {
                              "settings": {"type": "object", "properties": properties,
                                           "additionalProperties": True}}, "additionalProperties": True}},
                          "additionalProperties": True}
    schema = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "$id": "urn:traderesearch:configuration-editor:v1",
        "type": "object", "required": ["schema_version", "shared", "analyses", "ui"],
        "properties": {
            "schema_version": {"const": RESEARCH_CONFIGURATION_SCHEMA_VERSION, "type": "integer"},
            "shared": {"type": "object", "title": "Shared inputs" if english else "共享输入",
                       "properties": {"factors": {"type": "array", "items": {"type": "object"}}},
                       "additionalProperties": True},
            "analyses": {"type": "object", "title": "Analyses" if english else "分析配置",
                         "properties": analyses, "additionalProperties": True},
            "ui": {"type": "object", "title": "Display preferences" if english else "显示偏好",
                   "additionalProperties": True},
        },
        # Preserve extension fields; freezing remains the server's authority.
        "additionalProperties": True,
    }
    return {"schema_version": 1, "configuration_schema_version": RESEARCH_CONFIGURATION_SCHEMA_VERSION,
            "schema": schema, "catalog": catalog}
