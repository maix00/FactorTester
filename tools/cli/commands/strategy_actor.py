"""Static inspection and scaffolding for user-authored Strategy Actors."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import click


def register_strategy_actor_commands(strategy_group) -> None:
    actor = click.Group("actor", help="检查或生成独立 Strategy Actor 源码包。")
    strategy_group.add_command(actor)

    @actor.command("inspect")
    @click.argument("source", type=click.Path(exists=True, dir_okay=False, path_type=Path))
    @click.option("--json", "as_json", is_flag=True, help="输出机器可读 JSON")
    def inspect_actor(source: Path, as_json: bool) -> None:
        try:
            tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        except (OSError, SyntaxError) as exc:
            raise click.ClickException(f"cannot inspect actor: {exc}") from exc
        classes = []
        callbacks = set()
        imports = []
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                imports.append(ast.unparse(node))
            if isinstance(node, ast.ClassDef):
                methods = [item.name for item in node.body if isinstance(item, ast.FunctionDef)]
                class_callbacks = {name for name in methods if name.startswith("on_")}
                callbacks.update(class_callbacks)
                classes.append({"name": node.name, "callbacks": sorted(class_callbacks)})
        result = {
            "valid_python": True,
            "path": str(source.resolve()),
            "classes": classes,
            "callbacks": sorted(callbacks),
            "imports": imports,
            "execution": "static_only",
        }
        _emit(result, as_json)

    @actor.command("scaffold")
    @click.argument("name")
    @click.option("--output", required=True, type=click.Path(file_okay=False, path_type=Path))
    @click.option("--event", type=click.Choice(["bar", "market_feed"]), default="bar")
    @click.option("--json", "as_json", is_flag=True, help="输出机器可读 JSON")
    def scaffold_actor(name: str, output: Path, event: str, as_json: bool) -> None:
        if not name.isidentifier():
            raise click.ClickException("actor name must be a Python identifier")
        target = output.expanduser().resolve()
        target.mkdir(parents=True, exist_ok=False)
        (target / "__init__.py").write_text("", encoding="utf-8")
        callback = "on_bar" if event == "bar" else "on_market_feed"
        source = (
            "from tools.testers.backtest.engines.native.strategy import Strategy\n\n"
            f"class {name}(Strategy):\n"
            "    def on_start(self, context):\n"
            "        return None\n\n"
            f"    def {callback}(self, context, event):\n"
            "        return None\n\n"
            "    def on_stop(self, context):\n"
            "        return None\n"
        )
        (target / "actor.py").write_text(source, encoding="utf-8")
        manifest = {"schema_version": 1, "kind": "strategy-actor", "name": name, "entrypoint": "actor.py"}
        (target / "strategy.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        _emit({"created": True, "path": str(target), "manifest": manifest}, as_json)


def _emit(value: Any, as_json: bool) -> None:
    if as_json:
        click.echo(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        click.echo(" · ".join(f"{key}={item}" for key, item in value.items()))
