"""CLI for user-facing strategy templates and StrategySpec validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import click

from tools.cli.core.strategy_spec import BUILTIN_TEMPLATES, load_spec, template_for


@click.group("strategy")
def strategy() -> None:
    """选择、校验和查看回测策略声明，不暴露内部 Flow 或 StrategyBook。"""


@strategy.command("list")
@click.option("--json", "as_json", is_flag=True, help="输出机器可读 JSON")
def list_strategies(as_json: bool) -> None:
    rows = [
        {"source": f"builtin:{item.key}", "label": item.label, "description": item.description}
        for item in BUILTIN_TEMPLATES
    ]
    rows.append({"source": "profile:<path>", "label": "自定义 Actor", "description": "加载 Profile 中的 Strategy Actor"})
    _emit(rows, as_json)


@strategy.group("template")
def template() -> None:
    """查看内置策略模板。"""


@template.command("list")
@click.option("--json", "as_json", is_flag=True, help="输出机器可读 JSON")
def list_templates(as_json: bool) -> None:
    rows = [
        {
            "key": item.key,
            "source": f"builtin:{item.key}",
            "label": item.label,
            "description": item.description,
            "parameters": list(item.parameters),
        }
        for item in BUILTIN_TEMPLATES
    ]
    _emit(rows, as_json)


@template.command("show")
@click.argument("key")
@click.option("--json", "as_json", is_flag=True, help="输出机器可读 JSON")
def show_template(key: str, as_json: bool) -> None:
    try:
        item = template_for(key)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    _emit(
        {
            "key": item.key,
            "source": f"builtin:{item.key}",
            "label": item.label,
            "description": item.description,
            "parameters": list(item.parameters),
        },
        as_json,
    )


@strategy.command("validate")
@click.option(
    "--spec",
    "spec_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--json", "as_json", is_flag=True, help="输出机器可读 JSON")
def validate_strategy(spec_path: Path, as_json: bool) -> None:
    try:
        spec = load_spec(spec_path)
        if spec.source_kind == "builtin":
            template_for(spec.source_name)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    _emit(
        {"valid": True, "path": str(spec_path.resolve()), "strategy": spec.normalized()},
        as_json,
    )


def _emit(value: Any, as_json: bool) -> None:
    if as_json:
        click.echo(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))
        return
    rows = value if isinstance(value, list) else [value]
    for row in rows:
        if isinstance(row, dict):
            click.echo(" · ".join(f"{key}={item}" for key, item in row.items()))
        else:
            click.echo(str(row))
