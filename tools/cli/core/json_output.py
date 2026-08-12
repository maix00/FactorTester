"""Consistent JSON presentation for native CLI commands."""

from __future__ import annotations

import json
from typing import Any

import click


def json_text(value: Any, *, compact: bool = False) -> str:
    """Serialize CLI JSON predictably for people or compact transport."""
    if compact:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def echo_json(value: Any, *, compact: bool = False) -> None:
    click.echo(json_text(value, compact=compact))
