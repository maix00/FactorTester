"""Individual compatibility checks shared by authoring and validation."""

from __future__ import annotations

from typing import Any

from tools.testers.analysis_graph import AnalysisTargetOrigin

from .contracts import AnalysisAttachmentIssue


def issue(code: str, message: str, **details: Any) -> AnalysisAttachmentIssue:
    return AnalysisAttachmentIssue(code, message, details)


def check_refs(refs, cores, nodes, issues) -> None:
    if len(refs) != len(set(refs)):
        issues.append(issue("duplicate_target", "不能重复选择同一个分析目标"))
    unknown = sorted(ref for ref in refs if ref not in cores and ref not in nodes)
    if unknown:
        issues.append(issue(
            "unknown_target", "存在无法识别的分析目标", target_refs=unknown,
        ))


def check_count(definition, refs, issues) -> None:
    contract = definition.input_contract
    if len(refs) < contract.minimum_targets or (
        contract.maximum_targets is not None
        and len(refs) > contract.maximum_targets
    ):
        issues.append(issue(
            "target_count", "所选目标数量不符合该分析的输入基数",
            minimum=contract.minimum_targets,
            maximum=contract.maximum_targets,
            actual=len(refs),
        ))


def check_origins(definition, refs, cores, issues) -> None:
    accepted = set(definition.input_contract.target_origins)
    actual = {
        AnalysisTargetOrigin.CORE if ref in cores else AnalysisTargetOrigin.ANALYSIS
        for ref in refs
    }
    if actual - accepted:
        issues.append(issue(
            "target_origin", "所选目标所在层级不能挂载该分析",
            accepted=sorted(item.value for item in accepted),
            actual=sorted(item.value for item in actual),
        ))


def check_kinds(definition, refs, cores, nodes, issues) -> None:
    accepted = set(definition.input_contract.accepted_kinds)
    incompatible = {
        ref: sorted(kinds)
        for ref in refs
        if accepted.isdisjoint(
            kinds := output_kinds(ref, cores, nodes)
        )
    }
    if incompatible:
        issues.append(issue(
            "target_kind", "所选结果类型不能作为该分析的输入",
            accepted=sorted(accepted), actual=incompatible,
        ))


def output_kinds(ref, cores, nodes) -> set[str]:
    if ref in cores:
        return set(cores[ref].output_kinds)
    from ..registry import ic_analysis_graph_definition

    return {
        ic_analysis_graph_definition().type_by_key(
            nodes[ref].analysis_type,
        ).output_kind,
    }


def check_axes(definition, refs, cores, issues) -> None:
    contract = definition.input_contract
    core_targets = [cores[ref] for ref in refs if ref in cores]
    if len(core_targets) != len(refs):
        return
    for axis in contract.same_axes:
        if len({item.axis_value(axis) for item in core_targets}) > 1:
            issues.append(issue(
                "same_axis", f"所选目标必须具有相同的 {axis}", axis=axis,
            ))
    for axis in contract.varying_axes:
        if len({item.axis_value(axis) for item in core_targets}) < 2:
            issues.append(issue(
                "varying_axis", f"所选目标必须包含不同的 {axis}", axis=axis,
            ))


def check_core_inputs(definition, refs, cores, issues) -> None:
    required = set(definition.required_core_inputs)
    if not required:
        return
    core_targets = [cores[ref] for ref in refs if ref in cores]
    if len(core_targets) != len(refs):
        return
    available = set.intersection(
        *(set(item.output_kinds) for item in core_targets),
    ) if core_targets else set()
    missing = sorted(required - available)
    if missing:
        issues.append(issue(
            "core_input", "核心测试没有保留该分析所需的输入", missing=missing,
        ))


def check_cycle(editing_node_id, refs, nodes, issues) -> None:
    if not editing_node_id or editing_node_id not in nodes:
        return

    def reaches_editing(ref: str, visited: set[str]) -> bool:
        if ref == editing_node_id:
            return True
        if ref not in nodes or ref in visited:
            return False
        visited.add(ref)
        return any(
            reaches_editing(target, visited)
            for target in nodes[ref].target_refs
        )

    if any(reaches_editing(ref, set()) for ref in refs):
        issues.append(issue("cycle", "该挂载会在分析图中形成循环依赖"))


__all__ = [
    "check_axes", "check_core_inputs", "check_count", "check_cycle",
    "check_kinds", "check_origins", "check_refs", "output_kinds",
]
