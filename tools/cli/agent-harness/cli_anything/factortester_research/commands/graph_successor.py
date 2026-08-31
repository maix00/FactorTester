"""Token-bounded inspection commands for the successor Graph."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import click

from ..core.successor_graph import build_successor_graph
from ..core.trial_plan_fixture import (
    validate_trial_plan_fixture,
)
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
    category_by_id = {
        str(item["category_id"]): item
        for item in graph_value["requirement_catalog"]["categories"]
    }
    payload = {
        "graph_ref": (
            f"{graph_value['graph_id']}@{graph_value['version']}:"
            f"{graph_value['content_hash']}"
        ),
        "anchor_kind": anchor_kind,
        "anchor_ref": anchor_ref,
        "category_contexts": _category_contexts(
            compact,
            category_by_id=category_by_id,
            requirement_by_id=requirement_by_id,
            include_contracts=include_contracts,
        ),
        "requirements": compact,
        "report_requirements": [
            _report_projection(report_by_id[item], include_contracts)
            for item in report_ids
            if include_contracts or not item.startswith("report.requirement.")
        ],
    }
    if not include_contracts and any(
        item.startswith("report.requirement.") for item in report_ids
    ):
        payload["requirement_report_policy"] = {
            "id_template": "report.requirement.<requirement_id>",
            "method_ref": "adjudicate",
            "subject_kind": "verification_obligation_or_requirement",
            "coverage": "one item for every listed requirement subject",
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
        "report_requirement_refs": item["report_requirement_refs"],
    }


def _category_contexts(
    requirements: list[dict[str, Any]],
    *,
    category_by_id: dict[str, dict[str, Any]],
    requirement_by_id: dict[str, dict[str, Any]],
    include_contracts: bool,
) -> list[dict[str, Any]]:
    if include_contracts:
        return []
    category_ids = sorted({
        str(item["requirement_id"]).split(".", 1)[0]
        for item in requirements
    })
    values = []
    for category_id in category_ids:
        matching = next(
            requirement_by_id[str(item["requirement_id"])]
            for item in requirements
            if str(item["requirement_id"]).startswith(f"{category_id}.")
        )
        category = category_by_id[category_id]
        values.append({
            "category_id": category_id,
            "title_zh": category["title_zh"],
            "description_zh": category["description_zh"],
            "industry_principle_zh": matching["industry_principle_zh"],
            "industry_basis_refs": matching["industry_basis_refs"],
            "resolver_capability_ids": matching["resolver_capability_ids"],
        })
    return values


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


@click.command("trial-plan-check")
@click.argument(
    "document_file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--json", "as_json", is_flag=True, help="输出 JSON。")
def graph_trial_plan_check(
    document_file: Path,
    as_json: bool,
) -> None:
    """Validate one TrialPlan and its bounded RunSpec control summaries."""
    document = json.loads(document_file.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise click.ClickException("TrialPlan document must be an object")
    try:
        result = validate_trial_plan_fixture(
            document.get("trial_plan"),
            validation_contract=document.get("validation_contract"),
            action_input_summaries=document.get("action_input_summaries"),
            run_spec_summaries=document.get("run_spec_summaries"),
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    if as_json:
        echo_json(result)
        return
    click.echo("TrialPlan research sequence: passed")
    click.echo(" → ".join(result["ordered_action_ids"]))


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
