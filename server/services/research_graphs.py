"""Stable public façade for Research Graph application services."""

from server.services import agent_flow
from server.services.research_graph.activation_orchestration import (
    activate_reviewed_graph,
    activation_preflight,
)
from server.services.research_graph.active_pointer import (
    activate_graph,
    load_active_graph,
    rollback_active_graph,
)
from server.services.research_graph.branch.context import (
    build_graph_branch_context,
)
from server.services.research_graph.branch.continuation import (
    continue_graph_branch,
    preview_graph_continuation,
)
from server.services.research_graph.branch.cycle_objects import (
    load_research_cycle_object,
)
from server.services.research_graph.branch.next_packet import (
    build_graph_branch_edge_info,
    build_graph_branch_next,
)
from server.services.research_graph.branch.requirement_read import (
    load_current_graph_requirement,
)
from server.services.research_graph.branch.repository import (
    store_current_branch_resolution as _store_current_branch_resolution,
)
from server.services.research_graph.branch.runtime import (
    create_graph_instance,
    fork_graph_branch,
    load_graph_branch,
)
from server.services.research_graph.branch.handoff import (
    handoff_graph_branch,
)
from server.services.research_graph.branch.human_gate_override import (
    authorize_for_branch as authorize_human_gate_override,
    load_for_branch as load_human_gate_override,
)
from server.services.research_graph.branch.transition import (
    advance_graph_branch,
)
from server.services.research_graph.governance_workflow import (
    authorize_graph_activation,
    record_audit,
    record_proposal,
    record_proposal_review,
)
from server.services.research_graph.upgrade_validation import (
    derive_upgrade_validation,
    record_upgrade_validation,
)
from server.services.research_graph.draft_revision import (
    revise_unused_draft,
)
from server.services.research_graph.protocol import (
    GraphActivationBlocked,
    GraphVersionConflict,
)
from server.services.research_graph.packet_budget import (
    active_runtime_packet_budget_configuration,
    configure_runtime_packet_budget_profile,
)
from server.services.research_graph.proposal_review_packet import (
    load_proposal_review_packet,
)
from server.services.research_graph.schema import ensure_schema
from server.services.research_graph.presentation_contract import (
    DEFAULT_GRAPH_LOCALE,
    SUPPORTED_GRAPH_LOCALES,
    normalize_graph_locale,
    presentation_content_hash,
    validate_presentation,
)
from server.services.research_graph.presentations import (
    attach_presentation,
    list_presentations,
    load_presentation,
    register_presentation,
)
from server.services.research_graph.versions import (
    clear_graph_cache_for_current_db as _clear_graph_cache_for_current_db,
    list_graph_versions,
    load_graph,
    register_graph,
)
from server.services.research_graph.yaml_export import (
    graph_definition,
    graph_yaml_bytes,
    graph_yaml_filename,
)
from tools.data.sqlite.db import connect_sqlite


__all__ = [
    "GraphActivationBlocked",
    "GraphVersionConflict",
    "DEFAULT_GRAPH_LOCALE",
    "SUPPORTED_GRAPH_LOCALES",
    "activate_reviewed_graph",
    "activation_preflight",
    "activate_graph",
    "advance_graph_branch",
    "active_runtime_packet_budget_configuration",
    "authorize_graph_activation",
    "build_graph_branch_context",
    "build_graph_branch_edge_info",
    "build_graph_branch_next",
    "continue_graph_branch",
    "configure_runtime_packet_budget_profile",
    "create_graph_instance",
    "ensure_schema",
    "fork_graph_branch",
    "graph_definition",
    "graph_yaml_bytes",
    "graph_yaml_filename",
    "handoff_graph_branch",
    "authorize_human_gate_override",
    "list_graph_versions",
    "list_presentations",
    "load_active_graph",
    "load_graph",
    "load_graph_branch",
    "load_presentation",
    "load_human_gate_override",
    "load_proposal_review_packet",
    "load_current_graph_requirement",
    "load_research_cycle_object",
    "preview_graph_continuation",
    "record_audit",
    "record_proposal",
    "record_proposal_review",
    "derive_upgrade_validation",
    "record_upgrade_validation",
    "register_graph",
    "register_presentation",
    "revise_unused_draft",
    "rollback_active_graph",
    "attach_presentation",
    "normalize_graph_locale",
    "presentation_content_hash",
    "validate_presentation",
]
