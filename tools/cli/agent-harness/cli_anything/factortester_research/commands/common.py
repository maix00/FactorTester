"""Shared, token-stable CLI presentation helpers."""

import json
import click


def echo_json(payload: object) -> None:
    click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
