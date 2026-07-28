"""Shared Click options and bounded content parsing for report commands."""

from __future__ import annotations

import json
from pathlib import Path

import click


def scope_options(command):
    command = click.option("--profile", "profile_id", required=True)(command)
    command = click.option("--work-package-id", required=True)(command)
    command = click.option("--branch-id", required=True)(command)
    return click.option(
        "--release-profile", type=click.Path(
            exists=True, dir_okay=False, path_type=Path,
        ),
    )(command)


def component_content(
    *, kind: str, content_file: Path | None, code_file: Path | None,
    language: str, latex: str | None, fallback: str,
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
    if code_file is not None:
        return {"language": language, "code": code_file.read_text(encoding="utf-8")}
    if latex is not None:
        return {"latex": latex, "fallback": fallback}
    return read_json(content_file) if content_file else None


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
