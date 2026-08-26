"""Thin JSON delegates to the native fragment-bound Evidence CLI."""

from __future__ import annotations

import json

import click

from ..utils.factortester_backend import run_factortester
from .common import echo_json


_PASSTHROUGH = {
    "context_settings": {
        "ignore_unknown_options": True,
        "allow_extra_args": True,
    },
}


@click.group("evidence")
def evidence() -> None:
    """Use the native SourceCapture/Fragment/Evidence workflow."""


def _leaf(parent: click.Group, name: str, prefix: list[str]) -> None:
    @parent.command(name, **_PASSTHROUGH)
    @click.argument("args", nargs=-1, type=click.UNPROCESSED)
    def command(args: tuple[str, ...]) -> None:
        _forward([*prefix, *args])


def _group(parent: click.Group, name: str) -> click.Group:
    child = click.Group(name)
    parent.add_command(child)
    return child


for _name in (
    "guide", "create", "get", "search", "admit", "admit-graph", "exclude",
    "restore",
):
    _leaf(evidence, _name, ["research", "evidence", _name])

_source = _group(evidence, "source")
for _name in (
    "capture-job", "capture-terminal", "capture-file", "capture-url",
):
    _leaf(_source, _name, ["research", "evidence", "source", _name])

_fragment = _group(evidence, "fragment")
for _name in ("add", "list"):
    _leaf(_fragment, _name, ["research", "evidence", "fragment", _name])

_facet = _group(evidence, "facet")
_leaf(_facet, "list", ["research", "evidence", "facet", "list"])

_tag = _group(evidence, "tag")
for _name in (
    "list", "propose", "create", "update", "retire", "attach", "detach",
):
    _leaf(_tag, _name, ["research", "evidence", "tag", _name])


def _forward(argv: list[str]) -> None:
    command = list(argv)
    if "--json" not in command:
        command.append("--json")
    result = run_factortester(command, timeout=120)
    if result.returncode != 0:
        raise click.ClickException(
            (
                result.stderr
                or result.stdout
                or "FactorTester command failed"
            )[:2000]
        )
    try:
        echo_json(json.loads(result.stdout))
    except json.JSONDecodeError:
        click.echo(result.stdout.strip())
