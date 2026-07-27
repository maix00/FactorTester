"""CLI-Anything adapter for deterministic local research reports."""

from __future__ import annotations

import json
import uuid
from copy import deepcopy
from pathlib import Path

import click

from .common import echo_json


@click.group("report")
def report() -> None:
    """Create, edit, validate, and render Graph-independent reports."""


@report.command("chip-kinds")
@click.option("--locale", default="zh-Hans", show_default=True)
@click.option("--json", "as_json", is_flag=True)
def report_chip_kinds(locale: str, as_json: bool) -> None:
    from tools.cli.release.research_reporting.document.chips import chip_descriptor, chip_kinds

    value = {
        "locale": locale,
        "chips": [
            chip_descriptor({"kind": kind, "chip_id": "", "target_ref": ""}, locale=locale)
            for kind in chip_kinds()
        ],
    }
    if as_json:
        echo_json(value)
        return
    for item in value["chips"]:
        click.echo(f"{item['kind']}: {item['display_label']} -> {item['target']}")


@report.command("render")
@click.option(
    "--snapshot-file",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--workspace-root",
    required=True,
    type=click.Path(file_okay=False, path_type=Path),
)
@click.option("--json", "as_json", is_flag=True, help="输出 JSON。")
def report_render(
    snapshot_file: Path,
    workspace_root: Path,
    as_json: bool,
) -> None:
    """Render one content-addressed branch snapshot incrementally."""
    try:
        from ..core.reporting import render_branch_report

        snapshot = json.loads(snapshot_file.read_text())
        result = render_branch_report(
            snapshot,
            workspace_root=workspace_root,
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    payload = {
        key: str(value) if isinstance(value, Path) else value
        for key, value in result.items()
    }
    if as_json:
        echo_json(payload)
        return
    click.echo(f"report: {payload['path']}")
    click.echo(f"changed: {str(payload['changed']).lower()}")


@report.command("create")
@click.option("--file", required=True, type=click.Path(dir_okay=False, path_type=Path))
@click.option("--document-id", required=True)
@click.option("--title", required=True)
@click.option("--language", default="zh-Hans", show_default=True)
@click.option("--json", "as_json", is_flag=True)
def report_create(file: Path, document_id: str, title: str, language: str, as_json: bool) -> None:
    from tools.cli.release.research_reporting.document import (
        new_bindings, new_document, bindings_path_for, save_bindings, save_document,
    )

    value = save_document(file, new_document(document_id, title, language=language))
    bindings_file = bindings_path_for(file)
    save_bindings(bindings_file, new_bindings(value), value)
    _document_receipt(file, value, as_json, bindings_file=str(bindings_file))


@report.command("fork")
@click.option(
    "--source-file",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--output-file",
    required=True,
    type=click.Path(dir_okay=False, path_type=Path),
)
@click.option("--json", "as_json", is_flag=True)
def report_fork(source_file: Path, output_file: Path, as_json: bool) -> None:
    """Clone content and sidecar bindings for a new research branch.

    Graph ownership stays in the sidecar bindings; the content document never
    receives branch metadata. Existing historical bindings are retained and
    new branch-scoped chapters can be appended by ``cycle next``.
    """
    from tools.cli.release.research_reporting.document import (
        bindings_path_for, load_bindings, load_document, new_bindings,
        save_bindings, save_document,
    )

    output_bindings = bindings_path_for(output_file)
    if output_file.exists() or output_bindings.exists():
        raise click.ClickException(
            "output report or its bindings sidecar already exists"
        )
    source = load_document(source_file)
    source_bindings = load_bindings(
        bindings_path_for(source_file), source,
    )
    cloned = deepcopy(source)
    cloned["document_id"] = f"report-{uuid.uuid4().hex}"
    # The sidecar is revalidated against the new opaque document identity.
    cloned_bindings = new_bindings(cloned)
    cloned_bindings["bindings"] = deepcopy(source_bindings["bindings"])
    cloned_bindings["migration"] = deepcopy(source_bindings.get("migration"))
    value = save_document(output_file, cloned)
    save_bindings(output_bindings, cloned_bindings, value)
    payload = {
        "source_file": str(source_file),
        "output_file": str(output_file),
        "bindings_file": str(output_bindings),
        "source_document_id": source["document_id"],
        "document_id": value["document_id"],
        "component_count": len(value["components"]),
        "binding_count": len(cloned_bindings["bindings"]),
    }
    if as_json:
        echo_json(payload)
    else:
        click.echo(f"report fork: {output_file}")
        click.echo(f"components: {payload['component_count']}")
        click.echo(f"bindings: {payload['binding_count']}")


@report.command("add")
@click.option("--file", required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--component-id", required=True)
@click.option("--kind", required=True)
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
def report_add(
    file: Path, component_id: str, kind: str, title: str,
    parent_id: str | None, body: str, display_kind: str,
    content_file: Path | None, code_file: Path | None, language: str,
    latex: str | None, fallback: str,
    as_json: bool,
) -> None:
    from tools.cli.release.research_reporting.document import add_component, load_document, save_document

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
    from tools.cli.release.research_reporting.document import (
        bindings_path_for, load_bindings, rebind_document, save_bindings,
    )
    bindings_file = bindings_path_for(file)
    save_bindings(
        bindings_file, rebind_document(load_bindings(bindings_file), value), value,
    )
    _document_receipt(file, value, as_json, component_id=component_id)


@report.command("chip")
@click.option("--file", required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--component-id", required=True)
@click.option("--chip-id", required=True)
@click.option("--kind", required=True)
@click.option("--target-ref", required=True)
@click.option("--label", default="")
@click.option("--data-file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--json", "as_json", is_flag=True)
def report_chip(
    file: Path, component_id: str, chip_id: str, kind: str,
    target_ref: str, label: str, data_file: Path | None, as_json: bool,
) -> None:
    from tools.cli.release.research_reporting.document import (
        add_binding, bindings_path_for, load_bindings, load_document, save_bindings,
    )

    data = _read_json(data_file) if data_file else {}
    if not isinstance(data, dict):
        raise click.ClickException("--data-file must contain an object")
    document = load_document(file)
    bindings_file = bindings_path_for(file)
    bindings = load_bindings(bindings_file, document)
    value = add_binding(
        bindings, document, component_id=component_id, binding_id=chip_id,
        kind=kind, target_ref=target_ref, label=label, data=data,
    )
    save_bindings(bindings_file, value, document)
    _document_receipt(file, document, as_json, binding_id=chip_id)


@report.command("asset")
@click.option("--file", required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--asset-file", required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--json", "as_json", is_flag=True)
def report_asset(file: Path, asset_file: Path, as_json: bool) -> None:
    from tools.cli.release.research_reporting.document import (
        add_asset, bindings_path_for, load_bindings, load_document,
        rebind_document, save_bindings, save_document,
    )

    asset = _read_json(asset_file)
    if not isinstance(asset, dict):
        raise click.ClickException("--asset-file must contain an object")
    value = add_asset(load_document(file), asset)
    save_document(file, value)
    bindings_file = bindings_path_for(file)
    save_bindings(
        bindings_file, rebind_document(load_bindings(bindings_file), value), value,
    )
    _document_receipt(file, value, as_json, asset_ref=asset["asset_ref"])


@report.command("validate-document")
@click.option("--file", required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--json", "as_json", is_flag=True)
def report_validate_document(file: Path, as_json: bool) -> None:
    from tools.cli.release.research_reporting.document import bindings_path_for, load_bindings, load_document, validate_document

    value = validate_document(load_document(file))
    bindings = load_bindings(bindings_path_for(file), value)
    _document_receipt(file, value, as_json, valid=True, bindings=len(bindings["bindings"]))


@report.command("manifest")
@click.option("--file", required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--json", "as_json", is_flag=True)
def report_manifest(file: Path, as_json: bool) -> None:
    """Emit a content-free receipt suitable for Graph navigation packets."""
    from tools.cli.release.research_reporting.document import (
        bindings_manifest, bindings_path_for, document_manifest, load_bindings,
        load_document,
    )

    document = load_document(file)
    value = document_manifest(document)
    bindings = load_bindings(bindings_path_for(file), document)
    _document_receipt(
        file, document, as_json, manifest=value,
        bindings_manifest=bindings_manifest(bindings, document),
    )


@report.command("render-document")
@click.option("--file", required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--output", required=True, type=click.Path(dir_okay=False, path_type=Path))
@click.option("--json", "as_json", is_flag=True)
def report_render_document(file: Path, output: Path, as_json: bool) -> None:
    from tools.cli.release.research_reporting.document import load_document, render_markdown

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(render_markdown(load_document(file)))
    _document_receipt(file, load_document(file), as_json, output=str(output))


@report.command("migrate-legacy")
@click.option("--legacy-root", required=True, type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--output", required=True, type=click.Path(dir_okay=False, path_type=Path))
@click.option("--json", "as_json", is_flag=True)
def report_migrate_legacy(legacy_root: Path, output: Path, as_json: bool) -> None:
    from tools.cli.release.research_reporting.document.migration import migrate_legacy_journal

    document_output = output
    bindings_output = output.with_suffix(output.suffix + ".bindings.json")
    value = migrate_legacy_journal(legacy_root, document_output, bindings_output)
    _document_receipt(
        document_output, value["document"], as_json,
        bindings_output=str(bindings_output),
        document_hash=value["document_hash"],
        bindings_hash=value["bindings_hash"],
        migrated_sections=value["metadata"].get("migrated_sections", 0),
        skipped_files=value["metadata"].get("skipped_files", 0),
    )


def _read_json(path: Path | None) -> object:
    if path is None:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise click.ClickException(f"invalid JSON file: {path}") from exc


def _document_receipt(file: Path, value: dict, as_json: bool, **extra: object) -> None:
    payload = {
        "file": str(file),
        "document_id": value["document_id"],
        "revision": value["revision"],
        "components": len(value["components"]),
        "bindings": len(value.get("bindings") or []),
        **extra,
    }
    if as_json:
        echo_json(payload)
        return
    click.echo(" · ".join(f"{key}={item}" for key, item in payload.items()))
