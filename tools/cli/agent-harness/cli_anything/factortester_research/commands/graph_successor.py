"""Token-bounded inspection commands for the successor Graph."""

from __future__ import annotations

from typing import Any

import click

from ..core.successor_graph import build_successor_graph
from .common import echo_json


@click.command("successor")
@click.option("--json", "as_json", is_flag=True, help="输出 JSON。")
def graph_successor(as_json: bool) -> None:
    """Inspect the schema-v2 successor candidate without activating it."""
    payload = build_successor_graph()
    if as_json:
        echo_json(payload)
        return
    click.echo(
        f"graph: {payload['graph_id']} v{payload['version']} "
        f"lifecycle={payload['lifecycle']}"
    )
    click.echo(f"content_hash: {payload['content_hash']}")
    click.echo(
        f"nodes: {len(payload['nodes'])} · edges: {len(payload['edges'])} · "
        f"requirements: {len(payload['requirement_catalog']['requirements'])}"
    )
    click.echo("说明: 这是未激活候选；既有研究不会自动切换图版本。")


@click.command("requirements")
@click.option("--node", "node_id", default="", help="查询节点 Entry Requirements。")
@click.option("--edge", "edge_id", default="", help="查询边对应的 Requirements。")
@click.option(
    "--system-gate",
    "system_gate",
    default="",
    help="查询 continuation_reentry、node_reentry 或 evidence_admission。",
)
@click.option(
    "--include-contracts",
    is_flag=True,
    help="人工审计时返回完整小类合同；默认只返回紧凑描述。",
)
@click.option("--json", "as_json", is_flag=True, help="输出 JSON。")
def graph_requirements(
    node_id: str,
    edge_id: str,
    system_gate: str,
    include_contracts: bool,
    as_json: bool,
) -> None:
    """Return only the descriptions needed at one local Graph anchor."""
    if sum(bool(value) for value in (node_id, edge_id, system_gate)) != 1:
        raise click.ClickException(
            "exactly one of --node, --edge, or --system-gate is required"
        )
    graph_value = build_successor_graph()
    report_by_id = {
        str(item["report_requirement_id"]): item
        for item in graph_value["report_requirements"]
    }
    requirement_by_id = {
        str(item["requirement_id"]): item
        for item in graph_value["requirement_catalog"]["requirements"]
    }
    anchor_kind, anchor_ref, requirement_ids, report_ids = _anchor_requirements(
        graph_value,
        node_id=node_id,
        edge_id=edge_id,
        system_gate=system_gate,
    )
    compact = [
        _requirement_projection(requirement_by_id[item], include_contracts)
        for item in sorted(requirement_ids)
    ]
    payload = {
        "graph_ref": (
            f"{graph_value['graph_id']}@{graph_value['version']}:"
            f"{graph_value['content_hash']}"
        ),
        "anchor_kind": anchor_kind,
        "anchor_ref": anchor_ref,
        "requirements": compact,
        "report_requirements": [
            _report_projection(report_by_id[item], include_contracts)
            for item in report_ids
        ],
    }
    if as_json:
        echo_json(payload)
        return
    click.echo(f"{anchor_kind}: {anchor_ref}")
    for item in compact:
        click.echo(f"- {item['requirement_id']}: {item['question_zh']}")


def _requirement_projection(item: dict[str, Any], include: bool) -> dict[str, Any]:
    if include:
        return item
    return {
        "requirement_id": item["requirement_id"],
        "question_zh": item["question_zh"],
        "industry_principle_zh": item["industry_principle_zh"],
        "industry_basis_refs": item["industry_basis_refs"],
        "resolver_capability_ids": item["resolver_capability_ids"],
        "report_requirement_refs": item["report_requirement_refs"],
    }


def _report_projection(item: dict[str, Any], include: bool) -> dict[str, Any]:
    if include:
        return item
    return {
        "report_requirement_id": item["report_requirement_id"],
        "method_ref": item["method_ref"],
        "title_zh": item["title_zh"],
    }


@click.command("source")
@click.argument("source_ref")
@click.option("--json", "as_json", is_flag=True, help="输出 JSON。")
def graph_source(source_ref: str, as_json: bool) -> None:
    """Lazy-load one industry source referenced by an obligation prompt."""
    graph_value = build_successor_graph()
    source = next(
        (
            item for item in graph_value["industry_basis_catalog"]
            if item["source_ref"] == source_ref
        ),
        None,
    )
    if source is None:
        raise click.ClickException(f"unknown industry source: {source_ref}")
    if as_json:
        echo_json(source)
        return
    click.echo(f"{source['source_ref']}: {source['title']}")
    click.echo(source["principle_zh"])
    for locator in source["locators"]:
        click.echo(f"- {locator}")


def _anchor_requirements(
    graph_value: dict[str, Any],
    *,
    node_id: str,
    edge_id: str,
    system_gate: str,
) -> tuple[str, str, set[str], list[str]]:
    if node_id:
        node = next(
            (item for item in graph_value["nodes"] if item["node_id"] == node_id),
            None,
        )
        if node is None:
            raise click.ClickException(f"unknown successor Graph node: {node_id}")
        return (
            "node",
            node_id,
            set(node["entry_requirement_refs"]),
            [*node["entry_report_refs"], *node["node_report_refs"]],
        )
    if edge_id:
        edge = next(
            (item for item in graph_value["edges"] if item["edge_id"] == edge_id),
            None,
        )
        if edge is None:
            raise click.ClickException(f"unknown successor Graph edge: {edge_id}")
        report_ids = list(edge["report_requirement_refs"])
        reports = {
            item["report_requirement_id"]: item
            for item in graph_value["report_requirements"]
        }
        return (
            "edge",
            edge_id,
            {reports[item]["requirement_ref"] for item in report_ids},
            report_ids,
        )
    report_ids = [
        item["report_requirement_id"]
        for item in graph_value["report_requirements"]
        if item["anchor_kind"] == "system_gate"
        and item["anchor_ref"] == system_gate
    ]
    if not report_ids:
        raise click.ClickException(f"unknown successor system gate: {system_gate}")
    return "system_gate", system_gate, set(), report_ids
