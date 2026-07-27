"""User-facing strategy templates and immutable StrategySpec validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class StrategyTemplate:
    key: str
    label: str
    description: str
    parameters: tuple[str, ...] = ()


BUILTIN_TEMPLATES: tuple[StrategyTemplate, ...] = (
    StrategyTemplate("group_quantile", "分组多空", "按横截面信号分组并生成目标仓位", ("groups", "rebalance")),
    StrategyTemplate("threshold", "阈值策略", "按信号阈值产生目标仓位", ("entry", "exit")),
    StrategyTemplate("long_short", "多空组合", "将多个信号角色组合成多空目标", ("long", "short")),
    StrategyTemplate("term_carry", "Carry 策略", "按期限结构生成 Carry 交易意图", ("near", "far")),
)


@dataclass(frozen=True)
class StrategySpec:
    source: str
    parameters: Mapping[str, Any] = field(default_factory=dict)
    data: Mapping[str, Any] = field(default_factory=dict)
    account: Mapping[str, Any] = field(default_factory=dict)
    execution: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "StrategySpec":
        if not isinstance(value, Mapping):
            raise ValueError("strategy spec must be an object")
        source = str(value.get("source") or "").strip()
        if not source:
            raise ValueError("strategy spec requires source")
        if not (source.startswith("builtin:") or source.startswith("profile:")):
            raise ValueError("strategy source must use builtin:<name> or profile:<path>")
        sections = {}
        for name in ("parameters", "data", "account", "execution"):
            section = value.get(name) or {}
            if not isinstance(section, Mapping):
                raise ValueError(f"strategy spec {name} must be an object")
            sections[name] = dict(section)
        return cls(source=source, **sections)

    @property
    def source_kind(self) -> str:
        return self.source.split(":", 1)[0]

    @property
    def source_name(self) -> str:
        return self.source.split(":", 1)[1]

    def normalized(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "source_kind": self.source_kind,
            "source_name": self.source_name,
            "parameters": dict(self.parameters),
            "data": dict(self.data),
            "account": dict(self.account),
            "execution": dict(self.execution),
        }


def template_for(key: str) -> StrategyTemplate:
    for template in BUILTIN_TEMPLATES:
        if template.key == key:
            return template
    raise ValueError(f"unknown strategy template: {key}")


def load_spec(path: Path) -> StrategySpec:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"cannot read strategy spec: {path}") from exc
    if path.suffix.lower() in {".yaml", ".yml"}:
        try:
            import yaml
        except ImportError as exc:
            raise ValueError("YAML strategy specs require PyYAML") from exc
        value = yaml.safe_load(text)
    else:
        import json

        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError("strategy spec must be JSON or YAML") from exc
    return StrategySpec.from_mapping(value)
