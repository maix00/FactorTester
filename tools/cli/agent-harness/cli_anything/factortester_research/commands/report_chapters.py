"""CLI command for idempotent report chapter synchronization."""

from __future__ import annotations

import json
from pathlib import Path

import click

from tools.cli.release.research_reporting.document import (
    bindings_path_for,
    ensure_report_chapters,
    load_bindings,
    load_document,
    save_bindings,
    save_document,
)

from .common import echo_json


@click.command("sync-chapters")
@click.option(
    "--file",
    "report_file",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--packet-file",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--json", "as_json", is_flag=True, help="输出 JSON。")
def report_sync_chapters(
    report_file: Path,
    packet_file: Path,
    as_json: bool,
) -> None:
    """根据一次 cycle next packet 创建缺失章节，重复执行不会重复写入。"""
    try:
        packet = json.loads(packet_file.read_text(encoding="utf-8"))
        if not isinstance(packet, dict):
            raise ValueError("cycle packet must be a JSON object")
        document = load_document(report_file)
        bindings_file = bindings_path_for(report_file)
        bindings = load_bindings(bindings_file, document)
        document, bindings, receipt = ensure_report_chapters(
            document, bindings, packet,
        )
        save_document(report_file, document)
        save_bindings(bindings_file, bindings, document)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    payload = {
        **receipt,
        "report_file": str(report_file),
        "bindings_file": str(bindings_file),
    }
    if as_json:
        echo_json(payload)
        return
    click.echo(
        f"chapters synchronized: created={receipt['created_count']} "
        f"existing={receipt['existing_count']}"
    )
