"""Static inspection and scaffolding for user-authored Strategy Actors."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import click

_STRATEGY_CALLBACKS = frozenset({
    "on_start", "on_stop", "on_event", "on_market_feed", "on_bar", "on_timer",
    "on_quote", "on_trade", "on_book_delta", "on_book_snapshot", "on_order_event",
    "on_order_blocked", "on_order_submitted", "on_order_accepted",
    "on_order_partially_filled", "on_order_pending_cancel", "on_order_pending_update",
    "on_order_filled", "on_order_canceled", "on_order_rejected", "on_order_expired",
    "on_position_event", "on_position_opened", "on_position_changed", "on_position_closed",
})


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
                method_nodes = [item for item in node.body if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))]
                methods = [item.name for item in method_nodes]
                class_callbacks = {name for name in methods if name.startswith("on_")}
                callbacks.update(class_callbacks)
                bases = [ast.unparse(base) for base in node.bases]
                classes.append({
                    "name": node.name,
                    "bases": bases,
                    "is_strategy": any(base.split(".")[-1] == "Strategy" for base in bases),
                    "callbacks": sorted(class_callbacks),
                    "unknown_callbacks": sorted(class_callbacks - _STRATEGY_CALLBACKS),
                    "signatures": {
                        item.name: len(item.args.args)
                        for item in method_nodes if item.name in _STRATEGY_CALLBACKS
                    },
                })
        valid_classes = [item for item in classes if item["is_strategy"]]
        invalid_signatures = [
            f"{item['name']}.{callback}"
            for item in valid_classes
            for callback, count in item["signatures"].items()
            if count < 2
        ]
        result = {
            "valid_python": True,
            "valid_actor": bool(valid_classes) and not any(item["unknown_callbacks"] for item in valid_classes) and not invalid_signatures,
            "valid": bool(valid_classes) and not any(item["unknown_callbacks"] for item in valid_classes) and not invalid_signatures,
            "path": str(source.resolve()),
            "classes": classes,
            "callbacks": sorted(callbacks),
            "imports": imports,
            "invalid_signatures": invalid_signatures,
            "execution": "static_only",
        }
        _emit(result, as_json)

    @actor.command("scaffold")
    @click.argument("name")
    @click.option("--output", required=True, type=click.Path(file_okay=False, path_type=Path))
    @click.option("--event", type=click.Choice(["bar", "market_feed"]), default="bar")
    @click.option("--strategy-id", default=None, help="运行时策略别名，默认使用 Actor 名称")
    @click.option("--workspace", type=click.Choice(["profile", "personal"]), default="profile")
    @click.option("--json", "as_json", is_flag=True, help="输出机器可读 JSON")
    def scaffold_actor(name: str, output: Path, event: str, strategy_id: str | None, workspace: str, as_json: bool) -> None:
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
        strategy_id = strategy_id or name
        source_prefix = "personal:" if workspace == "personal" else "profile:"
        manifest = {
            "schema_version": 2,
            "kind": "strategy-actor",
            "name": name,
            "source": f"{source_prefix}strategies/{name}/actor.py",
            "workspace": workspace,
            "strategy_id": strategy_id,
            "entrypoint": name,
            "parameters": {},
            "data": {},
            "account": {},
            "execution": {},
            "requirements": {},
        }
        (target / "strategy.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        _emit({"created": True, "path": str(target), "manifest": manifest}, as_json)


def _emit(value: Any, as_json: bool) -> None:
    if as_json:
        click.echo(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        click.echo(" · ".join(f"{key}={item}" for key, item in value.items()))
