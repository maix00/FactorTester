"""Mutating Work Package report-authoring commands."""

from __future__ import annotations

import json
from pathlib import Path

import click

from tools.cli.release.profile import load_profile_root
from tools.cli.release.research_reporting.authoring import (
    load_branch_authoring,
    save_branch_authoring,
)
from tools.cli.release.research_reporting.document import (
    add_asset,
    add_binding,
    add_component,
    rebind_document,
)

from .research_report_scope import (
    ensure_authoring,
    load_authoring,
    persist_descriptor,
    resolve_branch_report_scope,
)


def register_authoring_commands(group: click.Group) -> None:
    group.add_command(create_report)
    group.add_command(add_report_component)
    group.add_command(attach_report_chip)
    group.add_command(add_report_asset)


def _scope_options(command):
    command = click.option("--profile", "profile_id", required=True)(command)
    command = click.option("--work-package-id", required=True)(command)
    command = click.option("--branch-id", required=True)(command)
    return click.option(
        "--release-profile",
        type=click.Path(exists=True, dir_okay=False, path_type=Path),
    )(command)


@click.command("create")
@_scope_options
@click.option("--json", "as_json", is_flag=True)
def create_report(
    profile_id: str, work_package_id: str, branch_id: str,
    release_profile: Path | None, as_json: bool,
) -> None:
    """Initialize the exact branch-owned structured report source."""
    scope = resolve_branch_report_scope(
        client_root=load_profile_root(release_profile), profile_id=profile_id,
        work_package_id=work_package_id, branch_id=branch_id,
    )
    result = ensure_authoring(scope)
    _output({
        "document": str(result["paths"]["document"]),
        "bindings": str(result["paths"]["bindings"]),
        "revision": result["document"]["revision"],
        "git": result["git"],
    }, as_json)


@click.command("add")
@_scope_options
@click.option("--component-id", required=True)
@click.option("--kind", type=click.Choice([
    "chapter", "section", "subsection", "entry", "special", "table",
    "image", "code", "math", "result",
]), required=True)
@click.option("--title", required=True)
@click.option("--parent-id", default=None)
@click.option("--body", default="")
@click.option("--display-kind", default="")
@click.option("--content-file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--code-file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--language", default="text", show_default=True)
@click.option("--latex", default=None)
@click.option("--fallback", default="")
@click.option("--json", "as_json", is_flag=True)
def add_report_component(
    profile_id: str, work_package_id: str, branch_id: str,
    release_profile: Path | None, component_id: str, kind: str, title: str,
    parent_id: str | None, body: str, display_kind: str,
    content_file: Path | None, code_file: Path | None, language: str,
    latex: str | None, fallback: str, as_json: bool,
) -> None:
    """Add one structured component to the branch Work Package report."""
    content = _component_content(
        kind=kind, content_file=content_file, code_file=code_file,
        language=language, latex=latex, fallback=fallback,
    )
    scope = resolve_branch_report_scope(
        client_root=load_profile_root(release_profile), profile_id=profile_id,
        work_package_id=work_package_id, branch_id=branch_id,
    )
    ensure_authoring(scope)
    document, bindings, _ = load_branch_authoring(
        package_root=scope.package_root, branch_id=branch_id,
    )
    document = add_component(
        document, component_id=component_id, kind=kind, title=title,
        parent_id=parent_id, body=body, content=content,
        display_kind=display_kind,
    )
    saved = save_branch_authoring(
        package_root=scope.package_root, work_package_id=work_package_id,
        branch_id=branch_id, document=document,
        bindings=rebind_document(bindings, document),
    )
    persist_descriptor(scope, saved["descriptor"])
    _output({
        "component_id": component_id, "revision": saved["document"]["revision"],
        "git": saved["git"],
    }, as_json)


@click.command("chip")
@_scope_options
@click.argument("component_id")
@click.option("--chip-id", required=True)
@click.option("--kind", type=click.Choice([
    "evidence", "obligation", "task", "job", "claim", "artifact",
    "report_requirement", "graph_reference", "checkpoint", "run",
]), required=True)
@click.option("--target-ref", required=True)
@click.option("--label", default="")
@click.option("--data-file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--json", "as_json", is_flag=True)
def attach_report_chip(
    profile_id: str, work_package_id: str, branch_id: str,
    release_profile: Path | None, component_id: str, chip_id: str, kind: str,
    target_ref: str, label: str, data_file: Path | None, as_json: bool,
) -> None:
    """Attach one typed chip to a branch report component."""
    scope = resolve_branch_report_scope(
        client_root=load_profile_root(release_profile), profile_id=profile_id,
        work_package_id=work_package_id, branch_id=branch_id,
    )
    ensure_authoring(scope)
    loaded = load_authoring(scope)
    data = _read_json(data_file) if data_file else {}
    if not isinstance(data, dict):
        raise click.ClickException("--data-file must contain a JSON object")
    bindings = add_binding(
        loaded["bindings"], loaded["document"], component_id=component_id,
        binding_id=chip_id, kind=kind, target_ref=target_ref, label=label,
        data=data,
    )
    saved = save_branch_authoring(
        package_root=scope.package_root, work_package_id=work_package_id,
        branch_id=branch_id, document=loaded["document"], bindings=bindings,
    )
    persist_descriptor(scope, saved["descriptor"])
    _output({"binding_id": chip_id, "git": saved["git"]}, as_json)


@click.command("asset")
@_scope_options
@click.option("--asset-file", required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--json", "as_json", is_flag=True)
def add_report_asset(
    profile_id: str, work_package_id: str, branch_id: str,
    release_profile: Path | None, asset_file: Path, as_json: bool,
) -> None:
    """Register an existing Work Package asset in the branch report source."""
    scope = resolve_branch_report_scope(
        client_root=load_profile_root(release_profile), profile_id=profile_id,
        work_package_id=work_package_id, branch_id=branch_id,
    )
    ensure_authoring(scope)
    loaded = load_authoring(scope)
    asset = _read_json(asset_file)
    if not isinstance(asset, dict):
        raise click.ClickException("--asset-file must contain a JSON object")
    document = add_asset(loaded["document"], asset)
    saved = save_branch_authoring(
        package_root=scope.package_root, work_package_id=work_package_id,
        branch_id=branch_id, document=document,
        bindings=rebind_document(loaded["bindings"], document),
    )
    persist_descriptor(scope, saved["descriptor"])
    _output({"asset_ref": asset["asset_ref"], "git": saved["git"]}, as_json)


def _component_content(
    *, kind: str, content_file: Path | None, code_file: Path | None,
    language: str, latex: str | None, fallback: str,
) -> object:
    if sum(item is not None for item in (content_file, code_file, latex)) > 1:
        raise click.ClickException(
            "--content-file, --code-file and --latex are mutually exclusive"
        )
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
    return _read_json(content_file) if content_file else None


def _read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise click.ClickException(f"invalid JSON file: {path}") from exc


def _output(value: dict[str, object], as_json: bool) -> None:
    if as_json:
        click.echo(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))
        return
    for key, item in value.items():
        click.echo(f"{key}: {item}")
