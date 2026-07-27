"""CLI-Anything compatible, Graph-independent report commands."""

from __future__ import annotations

import json
from pathlib import Path

import click

from tools.cli.release.research_reporting.document import (
    add_asset,
    add_component,
    add_binding,
    bindings_manifest,
    bindings_path_for,
    document_manifest,
    load_bindings,
    load_document,
    new_document,
    new_bindings,
    rebind_document,
    render_markdown,
    save_document,
    save_bindings,
    validate_document,
)
from tools.cli.release.research_reporting.document.chips import chip_descriptor, chip_kinds
from tools.cli.release.research_reporting.document.migration import (
    migrate_legacy_journal,
)


@click.group("report")
def report() -> None:
    """Author Graph-independent reports; Swift clients only display them."""


@report.command("chip-kinds")
@click.option("--locale", default="zh-Hans", show_default=True)
@click.option("--json", "as_json", is_flag=True)
def list_chip_kinds(locale: str, as_json: bool) -> None:
    descriptors = [
        chip_descriptor({"kind": kind, "chip_id": "", "target_ref": ""}, locale=locale)
        for kind in chip_kinds()
    ]
    if as_json:
        click.echo(json.dumps({"locale": locale, "chips": descriptors}, ensure_ascii=False, indent=2, sort_keys=True))
        return
    for item in descriptors:
        click.echo(f"{item['kind']}: {item['display_label']} -> {item['target']}")


@report.command("create")
@click.argument("file", type=click.Path(dir_okay=False, path_type=Path))
@click.option("--document-id", required=True)
@click.option("--title", required=True)
@click.option("--language", default="zh-Hans", show_default=True)
@click.option("--json", "as_json", is_flag=True)
def create_report(file: Path, document_id: str, title: str, language: str, as_json: bool) -> None:
    value = save_document(file, new_document(document_id, title, language=language))
    bindings_file = bindings_path_for(file)
    bindings = save_bindings(bindings_file, new_bindings(value), value)
    _output({
        "file": str(file), "bindings_file": str(bindings_file),
        "revision": value["revision"], "document_id": document_id,
        "bindings": len(bindings["bindings"]),
    }, as_json)


@report.command("add")
@click.argument("file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--component-id", required=True)
@click.option("--kind", type=click.Choice([
    "chapter", "section", "subsection", "entry", "special", "table",
    "image", "code", "math", "result",
]), required=True)
@click.option("--title", required=True)
@click.option("--parent-id", default=None)
@click.option("--body", default="")
@click.option("--display-kind", default="", help="Special-section presentation kind.")
@click.option("--content-file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--code-file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--language", default="text", show_default=True)
@click.option("--latex", default=None)
@click.option("--fallback", default="")
@click.option("--json", "as_json", is_flag=True)
def add_report_component(
    file: Path, component_id: str, kind: str, title: str,
    parent_id: str | None, body: str, display_kind: str,
    content_file: Path | None, code_file: Path | None, language: str,
    latex: str | None, fallback: str,
    as_json: bool,
) -> None:
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
    content = (
        {"language": language, "code": code_file.read_text(encoding="utf-8")}
        if code_file is not None
        else {"latex": latex, "fallback": fallback} if latex is not None
        else _read_json(content_file) if content_file else None
    )
    value = add_component(
        load_document(file), component_id=component_id, kind=kind,
        title=title, parent_id=parent_id, body=body, content=content,
        display_kind=display_kind,
    )
    save_document(file, value)
    bindings_file = bindings_path_for(file)
    bindings = rebind_document(load_bindings(bindings_file), value)
    save_bindings(bindings_file, bindings, value)
    _output({"file": str(file), "component_id": component_id, "revision": value["revision"]}, as_json)


@report.command("chip")
@click.argument("file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("component_id")
@click.option("--chip-id", required=True)
@click.option("--kind", type=click.Choice([
    "evidence", "obligation", "task", "job", "claim", "artifact",
    "report_requirement", "graph_reference", "checkpoint", "run",
]), required=True)
@click.option(
    "--target-ref", required=True,
    help="Graph 注册的 report_requirement_id",
)
@click.option("--label", default="")
@click.option("--data-file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--json", "as_json", is_flag=True)
def attach_report_chip(
    file: Path, component_id: str, chip_id: str, kind: str,
    target_ref: str, label: str, data_file: Path | None, as_json: bool,
) -> None:
    document = load_document(file)
    bindings_file = bindings_path_for(file)
    bindings = load_bindings(bindings_file, document)
    data = _read_json(data_file) if data_file else {}
    if not isinstance(data, dict):
        raise click.ClickException("--data-file must contain a JSON object")
    value = add_binding(
        bindings, document, component_id=component_id, binding_id=chip_id,
        kind=kind, target_ref=target_ref, label=label, data=data,
    )
    save_bindings(bindings_file, value, document)
    _output({
        "file": str(file), "bindings_file": str(bindings_file),
        "binding_id": chip_id, "revision": document["revision"],
    }, as_json)


@report.command("asset")
@click.argument("file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--asset-file", required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--json", "as_json", is_flag=True)
def add_report_asset(file: Path, asset_file: Path, as_json: bool) -> None:
    asset = _read_json(asset_file)
    if not isinstance(asset, dict):
        raise click.ClickException("--asset-file must contain a JSON object")
    value = add_asset(load_document(file), asset)
    save_document(file, value)
    bindings_file = bindings_path_for(file)
    bindings = rebind_document(load_bindings(bindings_file), value)
    save_bindings(bindings_file, bindings, value)
    _output({"file": str(file), "asset_ref": asset["asset_ref"], "revision": value["revision"]}, as_json)


@report.command("validate")
@click.argument("file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--json", "as_json", is_flag=True)
def validate_report(file: Path, as_json: bool) -> None:
    value = validate_document(load_document(file))
    bindings = load_bindings(bindings_path_for(file), value)
    _output({
        "valid": True,
        "document_id": value["document_id"],
        "revision": value["revision"],
        "components": len(value["components"]),
        "bindings": len(bindings["bindings"]),
    }, as_json)


@report.command("show")
@click.argument("file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--json", "as_json", is_flag=True)
def show_report(file: Path, as_json: bool) -> None:
    value = load_document(file)
    bindings_file = bindings_path_for(file)
    bindings = load_bindings(bindings_file, value)
    if as_json:
        click.echo(json.dumps({"document": value, "bindings": bindings}, ensure_ascii=False, indent=2, sort_keys=True))
        return
    click.echo(f"{value['title']} · revision {value['revision']}")
    click.echo(f"components: {len(value['components'])} · bindings: {len(bindings['bindings'])}")


@report.command("manifest")
@click.argument("file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--json", "as_json", is_flag=True)
def manifest_report(file: Path, as_json: bool) -> None:
    """Emit a content-free receipt for one report document."""
    document = load_document(file)
    bindings_file = bindings_path_for(file)
    bindings = load_bindings(bindings_file, document)
    _output({
        "file": str(file), "bindings_file": str(bindings_file),
        "manifest": document_manifest(document),
        "bindings_manifest": bindings_manifest(bindings, document),
    }, as_json)


@report.command("render")
@click.argument("file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--output", required=True, type=click.Path(dir_okay=False, path_type=Path))
@click.option("--json", "as_json", is_flag=True)
def render_report(file: Path, output: Path, as_json: bool) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(render_markdown(load_document(file)))
    _output({"file": str(file), "output": str(output)}, as_json)


@report.command("migrate-legacy")
@click.argument("legacy_root", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--document-output", required=True, type=click.Path(dir_okay=False, path_type=Path))
@click.option("--bindings-output", required=True, type=click.Path(dir_okay=False, path_type=Path))
@click.option("--json", "as_json", is_flag=True)
def migrate_report(
    legacy_root: Path, document_output: Path, bindings_output: Path, as_json: bool,
) -> None:
    value = migrate_legacy_journal(legacy_root, document_output, bindings_output)
    _output({
        "document_output": str(document_output),
        "bindings_output": str(bindings_output),
        "document_hash": value["document_hash"],
        "bindings_hash": value["bindings_hash"],
        "components": len(value["document"]["components"]),
        "bindings": len(value["bindings"]["bindings"]),
        "migrated_sections": value["metadata"].get("migrated_sections", 0),
        "skipped_files": value["metadata"].get("skipped_files", 0),
    }, as_json)


def _read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise click.ClickException(f"invalid JSON file: {path}") from exc


def _output(value: dict[str, object], as_json: bool) -> None:
    if as_json:
        click.echo(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        for key, item in value.items():
            click.echo(f"{key}: {item}")
