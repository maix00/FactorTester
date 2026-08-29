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


def _navigation(page: object) -> tuple[dict, dict]:
    if not isinstance(page, dict):
        raise click.ClickException("no assisted page is currently open")
    assistance = page.get("assistance")
    navigation = assistance.get("navigation") if isinstance(assistance, dict) else None
    nodes = navigation.get("nodes") if isinstance(navigation, dict) else None
    root_id = str(navigation.get("root_id") or "") if isinstance(navigation, dict) else ""
    if not root_id or not isinstance(nodes, dict) or root_id not in nodes:
        raise click.ClickException(
            "assisted page did not register an Agent navigation contract"
        )
    return navigation, nodes


def _node_view(nodes: dict, node_id: str, *, include_value: bool = False) -> dict:
    node = nodes.get(node_id)
    if not isinstance(node, dict):
        raise click.ClickException(f"assistance navigation node was not found: {node_id}")
    child_ids = [str(value) for value in node.get("children") or []]
    result = {
        **node,
        "children": [
            {
                key: child.get(key)
                for key in ("id", "kind", "label", "summary", "mounted")
                if key in child
            }
            for child_id in child_ids
            if isinstance((child := nodes.get(child_id)), dict)
        ],
    }
    if not include_value:
        result.pop("value", None)
    return result


def _inspect_summary(page: object) -> object:
    if not isinstance(page, dict):
        return page
    assistance = page.get("assistance")
    if not isinstance(assistance, dict):
        return page
    navigation, nodes = _navigation(page)
    root_id = str(navigation["root_id"])
    root = nodes[root_id]
    children = [
        nodes.get(str(node_id)) for node_id in root.get("children") or []
    ]
    tabs = [
        {
            key: child.get(key)
            for key in ("id", "label", "mounted")
            if key in child
        }
        for child in children
        if isinstance(child, dict) and child.get("kind") == "tab"
    ]
    configuration_collection = next(({
        key: child.get(key)
        for key in ("id", "kind", "label", "summary")
        if key in child
    } for child in children if (
        isinstance(child, dict) and child.get("kind") == "collection"
    )), None)
    entries = tabs or [
        {
            key: child.get(key)
            for key in ("id", "kind", "label")
            if key in child
        }
        for child in children
        if isinstance(child, dict)
    ]
    return {
        "tab_id": page.get("tab_id"),
        "updated_at": page.get("updated_at"),
        "assistance": {
            key: assistance.get(key)
            for key in ("schema_version", "page_kind", "revision")
            if key in assistance
        },
        "page": {
            key: root.get(key)
            for key in ("id", "label")
            if key in root
        },
        "tabs" if tabs else "sections": entries,
        **({"configuration_collection": configuration_collection}
           if configuration_collection else {}),
        "usage": {
            "inspect_node": "factortester assist inspect --node <node-id>",
            "candidate_lookup": (
                "use the candidate_source command registered by the selected field"
            ),
        },
    }


def _draft_receipt(value: object) -> object:
    """Return draft metadata without echoing its potentially large document."""
    if not isinstance(value, dict):
        return value
    return {key: item for key, item in value.items() if key != "document"}


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
    "--node",
    default="",
    help="Inspect one page-registered semantic navigation node.",
)
@click.option(
    "--value",
    "include_value",
    is_flag=True,
    help="Include the selected node's current value.",
)
@click.pass_obj
@friendly_errors
def inspect(profile_id: str, node: str, include_value: bool) -> None:
    profile_id = _profile_id(profile_id)
    value = client_from_config().inspect_profile_agent_assistance(profile_id)
    page = value.get("page")
    if not node:
        result = _inspect_summary(page)
    else:
        _, nodes = _navigation(page)
        result = _node_view(nodes, node, include_value=include_value)
    click.echo(json.dumps(result, ensure_ascii=False, indent=2))


@assist.group("drafts")
def drafts() -> None:
    """Retain and apply structured page-assistance drafts."""


@drafts.command("create")
@_input_options
@click.option("--from-current", is_flag=True)
@click.pass_obj
@friendly_errors
def create_draft(
    profile_id: str,
    file: Path | None,
    use_stdin: bool,
    from_current: bool,
) -> None:
    if sum((bool(file), use_stdin, from_current)) != 1:
        raise click.ClickException(
            "choose exactly one of --file, --stdin, or --from-current"
        )
    value = client_from_config().create_profile_agent_assistance_draft(
        _profile_id(profile_id),
        None if from_current else _document(file, use_stdin),
        from_current=from_current,
    )
    click.echo(json.dumps(_draft_receipt(value.get("draft")), ensure_ascii=False, indent=2))


@drafts.command("patch")
@click.argument("draft_id")
@_input_options
@click.pass_obj
@friendly_errors
def patch_draft(
    profile_id: str,
    draft_id: str,
    file: Path | None,
    use_stdin: bool,
) -> None:
    value = client_from_config().patch_profile_agent_assistance_draft(
        _profile_id(profile_id), draft_id, _document(file, use_stdin),
    )
    click.echo(json.dumps(_draft_receipt(value.get("draft")), ensure_ascii=False, indent=2))


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
@click.option(
    "--document",
    "include_document",
    is_flag=True,
    help="Explicitly include the complete structured document.",
)
@click.pass_obj
@friendly_errors
def show_draft(profile_id: str, draft_id: str, include_document: bool) -> None:
    value = client_from_config().get_profile_agent_assistance_draft(
        _profile_id(profile_id),
        draft_id,
    )
    result = value if include_document else {
        **value,
        "draft": _draft_receipt(value.get("draft")),
    }
    click.echo(json.dumps(result, ensure_ascii=False, indent=2))


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
    result = client_from_config().apply_profile_agent_assistance(
        _profile_id(profile_id),
        draft_id=draft_id,
    )
    if result.get("queued") is True:
        click.echo(
            "Assistance draft queued; it will apply when the target page is active"
        )
    else:
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
