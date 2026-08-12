"""Static recovery edges for the dynamic capability-detour contract."""

from __future__ import annotations


RESUMABLE_NODES = (
    "hypothesis_preregistration",
    "data_contract",
    "factor_semantics",
    "validation_design",
    "trial_execution",
    "result_audit",
    "research_decision",
    "factor_improvement_required",
)
DETOUR_NODES = frozenset({
    "capability_gap",
    "capability_resolution",
    "skill_candidate_review",
    "code_improvement_required",
})

RESUME_EDGE_SPECS = tuple(
    (
        f"capability_resolution__resume_{node_id}",
        "capability_resolution",
        node_id,
        "other.unclassified_material_question",
    )
    for node_id in RESUMABLE_NODES
)


def resume_guard(edge_id: str, to_node: str) -> dict[str, str]:
    if not edge_id.startswith("capability_resolution__resume_"):
        return {}
    return {"capability_detour_resume_node": to_node}


def report_container_policy(node_id: str) -> dict[str, str]:
    if node_id in DETOUR_NODES:
        return {
            "kind": "special",
            "anchor_from": "capability_detour.resume_node",
            "episode_from": "capability_detour.episode_id",
        }
    return {"kind": "chapter", "anchor_from": "node.node_id"}
