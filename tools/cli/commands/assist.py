"""Atomically exchange one structured document with the active assisted page."""

from __future__ import annotations

import json
from pathlib import Path

import click

from tools.cli.agent_auth import load_capability
from tools.cli.core.context import client_from_config
from tools.cli.core.errors import friendly_errors


def _profile_id(requested: str) -> str:
    capability = load_capability()
    value = str(requested or "").strip()
    if capability is not None:
        if value and value != capability.profile_id:
            raise click.ClickException(
                "the active capability is signed for another Profile"
            )
        return capability.profile_id
    if not value:
        raise click.ClickException(
            "--profile-id is required outside a Profile Agent runtime"
        )
    return value


def _document(file: Path | None, use_stdin: bool) -> dict:
    if bool(file) == bool(use_stdin):
        raise click.ClickException("choose exactly one of --file or --stdin")
    raw = (
        click.get_text_stream("stdin").read() if use_stdin else file.read_text("utf-8")
    )
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise click.ClickException("assistance document must be a JSON object")
    return value


def _input_options(function):
    function = click.option("--stdin", "use_stdin", is_flag=True)(function)
    return click.option("--file", type=click.Path(path_type=Path, exists=True))(
        function
    )


def _pointer(value: object, pointer: str) -> object:
    path = str(pointer or "").strip()
    if not path or path == "/":
        return value
    if not path.startswith("/"):
        raise click.ClickException("--path must be a JSON Pointer starting with /")
    current = value
    for raw_part in path[1:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and part in current:
            current = current[part]
            continue
        if isinstance(current, list) and part.isdigit():
            index = int(part)
            if 0 <= index < len(current):
                current = current[index]
                continue
        raise click.ClickException(f"assistance path does not exist: {path}")
    return current


def _keys(value: object) -> list[str]:
    return sorted(str(key) for key in value) if isinstance(value, dict) else []


def _child_path(path: str, part: object) -> str:
    escaped = str(part).replace("~", "~0").replace("/", "~1")
    return f"{path.rstrip('/')}/{escaped}" if path != "/" else f"/{escaped}"


def _bounded(
    value: object,
    *,
    path: str,
    depth: int,
    offset: int,
    limit: int,
) -> object:
    if not isinstance(value, (dict, list)):
        return value
    if isinstance(value, dict):
        keys = list(value)
        selected = keys[offset:offset + limit]
        children = {}
        for key in selected:
            child = value[key]
            child_pointer = _child_path(path, key)
            children[key] = (
                _bounded(
                    child, path=child_pointer, depth=depth - 1,
                    offset=0, limit=limit,
                )
                if depth > 0 else {
                    "type": "object" if isinstance(child, dict) else "array",
                    "count": len(child),
                    "path": child_pointer,
                }
            ) if isinstance(child, (dict, list)) else child
        return {
            "type": "object",
            "path": path,
            "count": len(keys),
            "offset": offset,
            "limit": limit,
            "has_more": offset + len(selected) < len(keys),
            "properties": children,
        }
    selected = value[offset:offset + limit]
    items = []
    for index, child in enumerate(selected, start=offset):
        child_pointer = _child_path(path, index)
        items.append(
            _bounded(
                child, path=child_pointer, depth=depth - 1,
                offset=0, limit=limit,
            )
            if depth > 0 and isinstance(child, (dict, list)) else (
                {
                    "type": "object" if isinstance(child, dict) else "array",
                    "count": len(child),
                    "path": child_pointer,
                }
                if isinstance(child, (dict, list)) else child
            )
        )
    return {
        "type": "array",
        "path": path,
        "count": len(value),
        "offset": offset,
        "limit": limit,
        "has_more": offset + len(selected) < len(value),
        "items": items,
    }


def _inspect_summary(page: object) -> object:
    if not isinstance(page, dict):
        return page
    assistance = page.get("assistance")
    if not isinstance(assistance, dict):
        return page
    document = assistance.get("document")
    schema = assistance.get("document_schema")
    properties = schema.get("properties") if isinstance(schema, dict) else None
    return {
        "tab_id": page.get("tab_id"),
        "updated_at": page.get("updated_at"),
        "assistance": {
            key: assistance.get(key)
            for key in ("schema_version", "page_kind", "revision")
            if key in assistance
        },
        "document": {
            "kind": document.get("document_kind")
            if isinstance(document, dict) else None,
            "keys": _keys(document),
            "path": "/assistance/document",
        },
        "document_schema": {
            "required": list(schema.get("required") or [])
            if isinstance(schema, dict) else [],
            "properties": _keys(properties),
            "path": "/assistance/document_schema",
        },
        "usage": {
            "read_subtree": (
                "factortester assist inspect --path "
                "/assistance/document/<field>"
            ),
            "read_schema_subtree": (
                "factortester assist inspect --path "
                "/assistance/document_schema/properties/<field>"
            ),
            "paginate": "add --offset <n> --limit <n>; containers are always bounded",
        },
    }


@click.group("assist")
@click.option("--profile-id", default="", hidden=True)
@click.pass_context
def assist(context: click.Context, profile_id: str) -> None:
    """Inspect or atomically fill the page currently assisted by this Agent."""
    # Resolve the capability only when a command executes so Click can render
    # subcommand help in an ordinary shell without an Agent runtime.
    context.obj = profile_id


@assist.command("inspect")
@click.option(
    "--path",
    "paths",
    multiple=True,
    help="Print only the selected JSON Pointer subtree; repeat as needed.",
)
@click.option("--depth", type=click.IntRange(0, 3), default=1, show_default=True)
@click.option("--offset", type=click.IntRange(min=0), default=0, show_default=True)
@click.option("--limit", type=click.IntRange(1, 50), default=20, show_default=True)
@click.pass_obj
@friendly_errors
def inspect(
    profile_id: str,
    paths: tuple[str, ...],
    depth: int,
    offset: int,
    limit: int,
) -> None:
    profile_id = _profile_id(profile_id)
    value = client_from_config().inspect_profile_agent_assistance(profile_id)
    page = value.get("page")
    if not paths:
        result = _inspect_summary(page)
    elif len(paths) == 1:
        result = _bounded(
            _pointer(page, paths[0]), path=paths[0], depth=depth,
            offset=offset, limit=limit,
        )
    else:
        result = {
            path: _bounded(
                _pointer(page, path), path=path, depth=depth,
                offset=offset, limit=limit,
            )
            for path in paths
        }
    click.echo(json.dumps(result, ensure_ascii=False, indent=2))


@assist.group("drafts")
def drafts() -> None:
    """Retain and apply structured page-assistance drafts."""


@drafts.command("create")
@_input_options
@click.pass_obj
@friendly_errors
def create_draft(profile_id: str, file: Path | None, use_stdin: bool) -> None:
    value = client_from_config().create_profile_agent_assistance_draft(
        _profile_id(profile_id),
        _document(file, use_stdin),
    )
    click.echo(json.dumps(value.get("draft"), ensure_ascii=False, indent=2))


@drafts.command("list")
@click.pass_obj
@friendly_errors
def list_drafts(profile_id: str) -> None:
    value = client_from_config().list_profile_agent_assistance_drafts(
        _profile_id(profile_id),
    )
    click.echo(json.dumps(value, ensure_ascii=False, indent=2))


@drafts.command("show")
@click.argument("draft_id")
@click.pass_obj
@friendly_errors
def show_draft(profile_id: str, draft_id: str) -> None:
    value = client_from_config().get_profile_agent_assistance_draft(
        _profile_id(profile_id),
        draft_id,
    )
    click.echo(json.dumps(value, ensure_ascii=False, indent=2))


@drafts.command("validate")
@click.argument("draft_id")
@click.pass_obj
@friendly_errors
def validate_draft(profile_id: str, draft_id: str) -> None:
    client_from_config().validate_profile_agent_assistance(
        _profile_id(profile_id),
        draft_id,
    )
    click.echo("Assistance draft is valid")


@drafts.command("apply")
@click.argument("draft_id")
@click.pass_obj
@friendly_errors
def apply_draft(profile_id: str, draft_id: str) -> None:
    client_from_config().apply_profile_agent_assistance(
        _profile_id(profile_id),
        draft_id=draft_id,
    )
    click.echo("Assistance draft applied")


@drafts.command("delete")
@click.argument("draft_id")
@click.pass_obj
@friendly_errors
def delete_draft(profile_id: str, draft_id: str) -> None:
    client_from_config().delete_profile_agent_assistance_draft(
        _profile_id(profile_id),
        draft_id,
    )
    click.echo("Assistance draft deleted")
