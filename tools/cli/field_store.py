"""Python mirror of the frontend FieldStore core used by CLI edit flows."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any


UNSET = object()


def is_empty(value: Any) -> bool:
    return value is None or value == "" or value == []


@dataclass(slots=True)
class FieldStore:
    defaults: dict[str, dict[str, Any]] = field(default_factory=dict)
    explicit_values: dict[str, Any] = field(default_factory=dict)
    parent: "FieldStore | None" = None

    @classmethod
    def from_manifest(
        cls,
        manifest: Mapping[str, Any],
        *,
        values: Mapping[str, Any] | None = None,
        parent: "FieldStore | None" = None,
    ) -> "FieldStore":
        defaults = manifest.get("defaults") if isinstance(manifest, Mapping) else None
        if isinstance(defaults, Mapping):
            normalized = {
                str(key): dict(value) if isinstance(value, Mapping) else {"value": value}
                for key, value in defaults.items()
            }
        else:
            normalized = {}
            for setting in manifest.get("settings", []) if isinstance(manifest, Mapping) else []:
                if isinstance(setting, Mapping) and setting.get("key"):
                    normalized[str(setting["key"])] = dict(setting)
        return cls(defaults=normalized, explicit_values=dict(values or {}), parent=parent)

    def get(self, key: str, default: Any = None) -> Any:
        if key in self.explicit_values:
            return self.explicit_values[key]
        if key in self.defaults:
            return deepcopy(self.defaults[key].get("value"))
        return default

    def effective(self, key: str) -> Any:
        return self._effective(key, seen=set())

    def set(self, key: str, value: Any = UNSET) -> None:
        if value is UNSET:
            self.explicit_values.pop(key, None)
        else:
            self.explicit_values[key] = value

    def set_many(self, values: Mapping[str, Any]) -> None:
        for key, value in values.items():
            self.set(str(key), value)

    def delete(self, key: str) -> None:
        self.set(key, UNSET)

    def to_payload(self) -> dict[str, Any]:
        return deepcopy(self.explicit_values)

    def field(self, key: str) -> dict[str, Any]:
        return self.defaults.get(key, {})

    def is_visible(self, key: str) -> bool:
        rules = self.defaults.get(key, {}).get("rules") or {}
        return _condition_matches(self, rules.get("visible_if"))

    def is_editable(self, key: str) -> bool:
        meta = self.defaults.get(key, {})
        rules = meta.get("rules") or {}
        return self.is_visible(key) and _condition_matches(self, rules.get("editable_if"))

    def display_value(self, key: str) -> Any:
        """Return the value a client should show for a registered field.

        A value locked by a condition must not leak a stale manual override
        into previews.  This mirrors the Web ``displayValueFor`` contract.
        """
        meta = self.defaults.get(key, {})
        if self.is_editable(key):
            return self.effective(key)
        conditional = self.conditional_default(key)
        if conditional is not UNSET:
            return deepcopy(conditional)
        return deepcopy(meta.get("value"))

    def conditional_default(self, key: str) -> Any:
        meta = self.defaults.get(key, {})
        rules = meta.get("rules") or {}
        for source_key, mapping in (rules.get("default_if") or {}).items():
            source_value = self.effective(str(source_key))
            if not isinstance(mapping, Mapping):
                continue
            if source_value in mapping:
                return mapping[source_value]
            source_text = str(source_value)
            for candidate, value in mapping.items():
                if str(candidate) == source_text:
                    return value
        engine = self.effective("engine")
        if engine in (None, ""):
            engine = self.effective("engine_mode")
        by_engine = rules.get("engine_defaults") or {}
        if isinstance(by_engine, Mapping):
            if engine in by_engine:
                return by_engine[engine]
            engine_text = str(engine)
            for candidate, value in by_engine.items():
                if str(candidate) == engine_text:
                    return value
        return UNSET

    def validate_value(self, key: str, value: Any) -> None:
        if key not in self.defaults:
            raise ValueError(f"未注册字段: {key}")
        meta = self.defaults[key]
        descriptor = meta.get("value_descriptor") or {}
        options = descriptor.get("options") or []
        if options:
            allowed = {option.get("value") for option in options if isinstance(option, Mapping)}
            if value not in allowed:
                raise ValueError(f"字段 {key} 的值不合法: {value!r}，允许值: {', '.join(str(item) for item in allowed)}")
        value_type = descriptor.get("value_type")
        if value_type in {"number", "integer"}:
            try:
                numeric = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"字段 {key} 需要数字值: {value!r}") from exc
            minimum = descriptor.get("minimum")
            maximum = descriptor.get("maximum")
            if minimum is not None and numeric < minimum:
                raise ValueError(f"字段 {key} 小于最小值: {minimum}")
            if maximum is not None and numeric > maximum:
                raise ValueError(f"字段 {key} 大于最大值: {maximum}")
        if value_type == "boolean" and not isinstance(value, bool):
            if str(value).lower() not in {"true", "false", "1", "0", "yes", "no"}:
                raise ValueError(f"字段 {key} 需要布尔值: {value!r}")

    def _effective(self, key: str, *, seen: set[str]) -> Any:
        if key in seen:
            return self.get(key)
        seen.add(key)
        own = self.get(key)
        if not is_empty(own):
            return own

        field_meta = self.defaults.get(key, {})
        serialization = field_meta.get("serialization")
        if isinstance(serialization, Mapping):
            if serialization.get("fallback") == "candidates":
                candidate_field = serialization.get("candidate_field")
                if candidate_field:
                    candidate_value = self._effective(str(candidate_field), seen=seen)
                    if not is_empty(candidate_value):
                        return candidate_value
            shared_page_field = serialization.get("shared_page_field")
            if shared_page_field and self.parent is not None:
                parent_value = self.parent.effective(str(shared_page_field))
                if not is_empty(parent_value):
                    return parent_value
        return own


def visible_fields(store: FieldStore, *, tab_key: str | None = None) -> list[tuple[str, dict[str, Any]]]:
    fields: list[tuple[str, dict[str, Any]]] = []
    for key, meta in store.defaults.items():
        if tab_key is not None and meta.get("tab_key") != tab_key:
            continue
        if store.is_visible(key):
            fields.append((key, meta))
    return sorted(fields, key=lambda item: (item[1].get("order", 1000), item[1].get("label", item[0])))


def _condition_matches(store: FieldStore, condition: Any) -> bool:
    if not isinstance(condition, Mapping):
        return True
    for dep_key, allowed_values in condition.items():
        current = store.effective(str(dep_key))
        if isinstance(allowed_values, (list, tuple, set)):
            allowed = set(allowed_values)
        else:
            allowed = {allowed_values}
        if not any(current == candidate or str(current) == str(candidate) for candidate in allowed):
            return False
    return True
