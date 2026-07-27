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
    required_fields: tuple[str, ...] = ()
    required_data: tuple[str, ...] = ()
    actor_callbacks: tuple[str, ...] = ()


BUILTIN_TEMPLATES: tuple[StrategyTemplate, ...] = (
    StrategyTemplate(
        "group_quantile", "分组多空", "按横截面信号分组并生成目标仓位",
        ("groups", "rebalance"),
        ("factor", "products", "split_count", "group_index", "position_policy"),
        ("factor_value", "current_prices", "tradable_status"),
        ("on_start", "on_bar", "on_stop"),
    ),
    StrategyTemplate(
        "threshold", "阈值策略", "按信号阈值产生目标仓位", ("entry", "exit"),
        ("factor", "products", "entry_threshold", "exit_threshold"),
        ("factor_value", "current_prices", "tradable_status"),
        ("on_start", "on_bar", "on_stop"),
    ),
    StrategyTemplate(
        "long_short", "多空组合", "将多个信号角色组合成多空目标", ("long", "short"),
        ("long_strategy", "short_strategy", "gross_weight"),
        ("target_weights", "current_prices"),
        ("on_start", "on_bar", "on_stop"),
    ),
    StrategyTemplate(
        "term_carry", "Carry 策略", "按期限结构生成 Carry 交易意图", ("near", "far"),
        ("factor", "products", "near_rank", "far_rank"),
        ("term_structure", "current_prices", "tradable_status"),
        ("on_start", "on_bar", "on_stop"),
    ),
)


@dataclass(frozen=True)
class StrategySpec:
    source: str
    workspace: str = "profile"
    strategy_id: str = ""
    entrypoint: str = ""
    parameters: Mapping[str, Any] = field(default_factory=dict)
    data: Mapping[str, Any] = field(default_factory=dict)
    account: Mapping[str, Any] = field(default_factory=dict)
    execution: Mapping[str, Any] = field(default_factory=dict)
    requirements: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "StrategySpec":
        if not isinstance(value, Mapping):
            raise ValueError("strategy spec must be an object")
        source = str(value.get("source") or "").strip()
        if not source:
            raise ValueError("strategy spec requires source")
        if not any(source.startswith(prefix) for prefix in ("builtin:", "profile:", "personal:")):
            raise ValueError("strategy source must use builtin:<name>, profile:<path>, or personal:<path>")
        workspace = str(value.get("workspace") or "profile").strip()
        if workspace not in {"profile", "personal"} and not workspace.startswith("profile:"):
            raise ValueError("strategy workspace must be profile, personal, or profile:<id>")
        strategy_id = str(value.get("strategy_id") or "").strip()
        entrypoint = str(value.get("entrypoint") or "Strategy").strip()
        sections = {}
        for name in ("parameters", "data", "account", "execution", "requirements"):
            section = value.get(name) or {}
            if not isinstance(section, Mapping):
                raise ValueError(f"strategy spec {name} must be an object")
            sections[name] = dict(section)
        _validate_source_path(source)
        return cls(
            source=source,
            workspace=workspace,
            strategy_id=strategy_id,
            entrypoint=entrypoint,
            **sections,
        )

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
            "workspace": self.workspace,
            "strategy_id": self.strategy_id,
            "entrypoint": self.entrypoint,
            "parameters": dict(self.parameters),
            "data": dict(self.data),
            "account": dict(self.account),
            "execution": dict(self.execution),
            "requirements": dict(self.requirements),
        }

    def dependencies(self) -> dict[str, Any]:
        """Return semantic requirements without exposing internal Flows."""
        if self.source_kind != "builtin":
            return {
                "source_kind": self.source_kind,
                "source_name": self.source_name,
                "required_fields": sorted(self.requirements.get("fields", [])),
                "required_data": sorted(self.requirements.get("data", [])),
            }
        template = template_for(self.source_name)
        return {
            "source_kind": "builtin",
            "source_name": template.key,
            "required_fields": list(template.required_fields),
            "required_data": list(template.required_data),
            "actor_callbacks": list(template.actor_callbacks),
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


def _validate_source_path(source: str) -> None:
    kind, name = source.split(":", 1)
    if kind in {"profile", "personal"}:
        path = Path(name)
        if path.is_absolute() or ".." in path.parts or not name.strip():
            raise ValueError("strategy source path must be relative and stay in its workspace")
