"""Local graph inspection, capability resolution, and replay commands."""

from __future__ import annotations

import json
from pathlib import Path

import click

from ..core.capabilities import load_builtin_capability_registry, resolve_graph_capabilities
from ..core.graph import build_draft_graph, build_observed_graph, graph_content_hash
from ..core.replay import replay_graph_trace
from ..core.session import load_session
from .common import echo_json

@click.group("graph")
def graph() -> None:
    """Inspect research decision graphs without activating them."""


@graph.command("observed")
@click.option("--json", "as_json", is_flag=True, help="输出 JSON。")
@click.pass_context
def graph_observed(ctx: click.Context, as_json: bool) -> None:
    """Project the saved fixed plan and local gap states as an Observed Graph."""
    session = load_session(ctx.obj["session_path"])
    if not session.plan:
        raise click.ClickException("当前 session 没有研究计划；请先运行 plan")
    payload = build_observed_graph(session.plan)
    payload["content_hash"] = graph_content_hash(payload)
    if as_json:
        echo_json(payload)
        return
    click.echo(
        f"graph: {payload['graph_id']} v{payload['version']} "
        f"lifecycle={payload['lifecycle']}"
    )
    click.echo(f"content_hash: {payload['content_hash']}")
    click.echo(
        f"nodes: {len(payload['nodes'])} · edges: {len(payload['edges'])}"
    )
    click.echo("说明: observed graph 只描述现有 Harness，不约束实际研究。")


@graph.command("draft")
@click.option("--json", "as_json", is_flag=True, help="输出 JSON。")
def graph_draft(as_json: bool) -> None:
    """Inspect the product-neutral candidate for the first Active Graph."""
    payload = build_draft_graph()
    if as_json:
        echo_json(payload)
        return
    click.echo(
        f"graph: {payload['graph_id']} v{payload['version']} "
        f"lifecycle={payload['lifecycle']}"
    )
    click.echo(f"research_semantics: {payload['research_semantics']}")
    click.echo(f"content_hash: {payload['content_hash']}")
    click.echo(f"nodes: {len(payload['nodes'])} · edges: {len(payload['edges'])}")
    click.echo("说明: 产品组适用性由 capability binding 解析，不改变研究图拓扑。")


@graph.command("capabilities")
@click.option(
    "--product-group",
    required=True,
    help="实现适用的产品组，例如 china_futures；不用于改变研究图结构。",
)
@click.option(
    "--approve-implementation",
    "approved_implementation_ids",
    multiple=True,
    help="本次解析中已有审计授权的实现 ID；可重复。",
)
@click.option(
    "--node",
    "node_id",
    default="",
    help="只解析当前节点；默认 entry_node。",
)
@click.option(
    "--facts-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="供机器 predicate 使用的局部事实 JSON。",
)
@click.option(
    "--trigger-capability",
    "triggered_capability_ids",
    multiple=True,
    help="语义审查已明确触发的条件能力 ID；可重复。",
)
@click.option(
    "--all",
    "include_all",
    is_flag=True,
    help="仅 activation audit 使用：解析整张图。",
)
@click.option(
    "--include-contracts",
    is_flag=True,
    help="仅人工审计时返回完整 capability contracts；默认省略以节省 token。",
)
@click.option("--json", "as_json", is_flag=True, help="输出 JSON。")
def graph_capabilities(
    product_group: str,
    approved_implementation_ids: tuple[str, ...],
    node_id: str,
    facts_file: Path | None,
    triggered_capability_ids: tuple[str, ...],
    include_all: bool,
    include_contracts: bool,
    as_json: bool,
) -> None:
    """Resolve Draft Graph semantics to approved product implementations."""
    draft = build_draft_graph()
    registry = load_builtin_capability_registry()
    facts = (
        json.loads(facts_file.read_text(encoding="utf-8"))
        if facts_file is not None else {}
    )
    if not isinstance(facts, dict):
        raise click.ClickException("facts file must contain a JSON object")
    resolution = resolve_graph_capabilities(
        draft,
        registry,
        product_group=product_group,
        approved_implementation_ids=set(approved_implementation_ids),
        node_id=node_id or None,
        facts=facts,
        triggered_capability_ids=set(triggered_capability_ids),
        include_all=include_all,
    )
    selected_ids = {
        str(item.get("capability_id") or "")
        for key in (
            "bindings",
            "gaps",
            "triggered_conditional_bindings",
            "triggered_conditional_gaps",
            "undetermined_conditions",
        )
        for item in resolution.get(key) or []
    }
    contracts = [
        item for item in registry["capabilities"]
        if include_all or item["capability_id"] in selected_ids
    ]
    payload: dict[str, object] = {
        "product_group": product_group,
        "graph": {
            "graph_id": draft["graph_id"],
            "version": draft["version"],
            "lifecycle": draft["lifecycle"],
            "research_semantics": draft["research_semantics"],
            "content_hash": draft["content_hash"],
        },
        "resolution": resolution,
    }
    if include_contracts:
        payload["contracts"] = contracts
    if as_json:
        echo_json(payload)
        return
    click.echo(
        f"graph: {draft['graph_id']} v{draft['version']} "
        f"({draft['research_semantics']})"
    )
    click.echo(f"product_group: {product_group}")
    click.echo(
        f"scope: {resolution['scope']} · node: {resolution['node_id']}"
    )
    click.echo(f"approved_bindings: {len(resolution['bindings'])}")
    click.echo(f"capability_gaps: {len(resolution['gaps'])}")
    for item in resolution["gaps"]:
        click.echo(f"- {item['capability_id']}: {item['reason']}")


@graph.command("replay")
@click.argument(
    "trace_file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--json", "as_json", is_flag=True, help="输出 JSON。")
def graph_replay(trace_file: Path, as_json: bool) -> None:
    """在不提交任务或修改 artifact 的前提下回放历史研究 trace。"""
    trace = json.loads(trace_file.read_text(encoding="utf-8"))
    if not isinstance(trace, dict):
        raise click.ClickException("trace file must contain a JSON object")
    report = replay_graph_trace(build_draft_graph(), trace)
    if as_json:
        echo_json(report)
        return
    click.echo(
        f"status: {report['status']} · "
        f"external_mutations: {report['external_mutations']}"
    )
    click.echo(
        f"covered_edges: {len(report['coverage']['edge_ids'])}"
    )
