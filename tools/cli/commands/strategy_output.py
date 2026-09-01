"""Bounded human-readable output for Strategy library commands."""

from __future__ import annotations

import json
from typing import Any

import click


def emit_library(value: Any, as_json: bool = False) -> None:
    if as_json:
        _json(value)
        return
    if not isinstance(value, dict):
        click.echo(str(value))
        return
    if isinstance(value.get("items"), list):
        _library_list(value)
        return
    if isinstance(value.get("strategy"), dict):
        _library_strategy(value["strategy"])
        return
    if isinstance(value.get("revision"), dict):
        _library_revision(value["revision"])
        return
    if isinstance(value.get("revisions"), list):
        _library_revisions(value)
        return
    if isinstance(value.get("shares"), list):
        click.echo(
            f"strategy_ref={value.get('strategy_ref', '—')} "
            f"shares={len(value['shares'])}"
        )
        for principal in value["shares"]:
            click.echo(f"share={principal}")
        return
    _scalars(value)


def emit_workspace(value: Any, as_json: bool = False) -> None:
    if as_json:
        _json(value)
        return
    if not isinstance(value, dict):
        click.echo(str(value))
        return
    if isinstance(value.get("bindings"), list) or isinstance(
        value.get("strategies"), list
    ):
        click.echo(
            f"configuration_id={value.get('configuration_id', '—')} "
            f"revision={value.get('revision', '—')} "
            f"strategies={len(value.get('strategies') or [])} "
            f"bindings={len(value.get('bindings') or [])}"
        )
        for strategy in value.get("strategies") or []:
            _workspace_strategy(strategy)
        for binding in value.get("bindings") or []:
            _workspace_binding(binding)
        return
    if isinstance(value.get("binding"), dict):
        _workspace_binding(value["binding"])
        if isinstance(value.get("strategy"), dict):
            _workspace_strategy(value["strategy"])
        if isinstance(value.get("removed_strategy"), dict):
            click.echo("removed:")
            _workspace_strategy(value["removed_strategy"])
        return
    if isinstance(value.get("change"), dict):
        emit_workspace(value["change"])
        return
    _scalars(value)


def _library_list(value: dict[str, Any]) -> None:
    click.echo(
        f"scope={value.get('scope', '—')} page={value.get('page', '—')} "
        f"total={value.get('total', 0)}"
    )
    for item in value.get("items") or []:
        _library_row(item)


def _library_row(item: dict[str, Any]) -> None:
    revision = item.get("current_revision") or {}
    click.echo(
        f"strategy={item.get('name') or '—'} "
        f"ref={item.get('strategy_ref') or '—'} "
        f"owner={item.get('owner_ref') or '—'} "
        f"revision=r{revision.get('revision_number', '—')} "
        f"visibility={item.get('visibility') or '—'}"
    )


def _library_strategy(strategy: dict[str, Any]) -> None:
    click.echo(
        f"strategy={strategy.get('name') or '—'} "
        f"ref={strategy.get('strategy_ref') or '—'} "
        f"owner={strategy.get('owner_ref') or '—'} "
        f"visibility={strategy.get('visibility') or '—'}"
    )
    _library_revision(
        strategy.get("current_revision") or {}, prefix="current_revision",
    )


def _library_revisions(value: dict[str, Any]) -> None:
    click.echo(
        f"strategy_ref={value.get('strategy_ref', '—')} "
        f"revisions={len(value.get('revisions') or [])}"
    )
    for revision in value.get("revisions") or []:
        _library_revision(revision, prefix="revision")


def _library_revision(
    revision: dict[str, Any], prefix: str = "revision",
) -> None:
    click.echo(
        f"{prefix}={revision.get('revision_ref') or '—'} "
        f"number={revision.get('revision_number', '—')} "
        f"entrypoint={revision.get('entrypoint') or '—'} "
        f"sha256={revision.get('source_sha256') or '—'}"
    )
    hooks = [
        str(item.get("name") or item)
        if isinstance(item, dict) else str(item)
        for item in revision.get("hooks") or []
    ]
    if hooks:
        click.echo(f"hooks={','.join(hooks)}")
    if "source_code" in revision:
        click.echo("source_code:")
        click.echo(str(revision.get("source_code") or ""))


def _workspace_strategy(strategy: dict[str, Any]) -> None:
    click.echo(
        f"strategy={strategy.get('name') or strategy.get('temp_ref') or '—'} "
        f"temp_ref={strategy.get('temp_ref') or '—'} "
        f"entrypoint={strategy.get('entrypoint') or 'Strategy'} "
        f"sha256={strategy.get('source_sha256') or '—'}"
    )
    if "source_code" in strategy:
        click.echo("source_code:")
        click.echo(str(strategy.get("source_code") or ""))


def _workspace_binding(binding: dict[str, Any]) -> None:
    source = binding.get("source") or {}
    click.echo(
        f"binding={binding.get('binding_id') or '—'} "
        f"target={binding.get('target_strategy_id') or '—'} "
        f"kind={source.get('kind') or '—'}"
    )
    if source.get("kind") == "inline":
        click.echo(f"temp_ref={source.get('temp_ref') or '—'}")
    elif source.get("kind") == "library":
        click.echo(
            f"strategy_ref={source.get('strategy_ref') or '—'} "
            f"revision_ref={source.get('revision_ref') or '—'} "
            f"sha256={source.get('source_sha256') or '—'}"
        )


def _scalars(value: dict[str, Any]) -> None:
    for key, item in value.items():
        if not isinstance(item, (dict, list)):
            click.echo(f"{key}={item}")


def _json(value: Any) -> None:
    click.echo(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))
