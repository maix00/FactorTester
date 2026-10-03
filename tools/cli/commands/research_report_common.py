"""Shared Click options and bounded content parsing for report commands."""

from __future__ import annotations

import json
from pathlib import Path

import click


def scope_options(command):
    command = click.option("--profile", "profile_id", required=True)(command)
    command = click.option("--report-workspace-id", required=True)(command)
    command = click.option("--branch-id", required=True)(command)
    return click.option(
        "--release-profile", type=click.Path(
            exists=True, dir_okay=False, path_type=Path,
        ),
    )(command)


def component_content(
    *, kind: str, content_file: Path | None, code_file: Path | None,
    language: str, latex: str | None, fallback: str,
    items: tuple[str, ...] = (), ordered: bool = False,
) -> object:
    if sum(item is not None for item in (content_file, code_file, latex)) > 1:
        raise click.ClickException("--content-file, --code-file and --latex are mutually exclusive")
    if code_file is not None and kind != "code":
        raise click.ClickException("--code-file requires --kind code")
    if kind == "code" and content_file is None and code_file is None:
        raise click.ClickException("--kind code requires --code-file or --content-file")
    if latex is not None and kind != "math":
        raise click.ClickException("--latex requires --kind math")
    if fallback and kind != "math":
        raise click.ClickException("--fallback requires --kind math")
    if kind == "math" and content_file is None and latex is None:
        raise click.ClickException("--kind math requires --latex or --content-file")
    if items and kind != "list":
        raise click.ClickException("--item requires --kind list")
    if ordered and kind != "list":
        raise click.ClickException("--ordered requires --kind list")
    if kind == "list" and content_file is None and not items:
        raise click.ClickException("--kind list requires --item or --content-file")
    if kind == "list" and content_file is not None and items:
        raise click.ClickException("--content-file and --item are mutually exclusive")
    if code_file is not None:
        return {"language": language, "code": code_file.read_text(encoding="utf-8")}
    if latex is not None:
        return {"latex": latex, "fallback": fallback}
    if items:
        return {
            "style": "ordered" if ordered else "unordered",
            "items": [{"text": item, "depth": 0} for item in items],
        }
    return read_json(content_file) if content_file else None


def rich_body(*, body: str | None, body_file: Path | None) -> str:
    """Read the portable rich-text source without treating it as JSON."""
    if body is not None and body_file is not None:
        raise click.ClickException("--body and --body-file are mutually exclusive")
    if body_file is None:
        return body or ""
    try:
        return body_file.read_text(encoding="utf-8")
    except OSError as exc:
        raise click.ClickException(f"unable to read rich-text file: {body_file}") from exc


def read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise click.ClickException(f"invalid JSON file: {path}") from exc


def output(value: dict[str, object], as_json: bool) -> None:
    if as_json:
        click.echo(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))
        return
    for key, item in value.items():
        click.echo(f"{key}: {item}")
