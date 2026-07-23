"""Stable public façade for Research Graph application services."""

from server.services import agent_flow
from server.services.research_graph.activation_validation import (
    record_validation,
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
from server.services.research_graph.branch.transition import (
    advance_graph_branch,
)
from server.services.research_graph.governance_workflow import (
    authorize_graph_activation,
    record_audit,
    record_proposal,
    record_proposal_review,
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
from server.services.research_graph.schema import ensure_schema
from server.services.research_graph.versions import (
    clear_graph_cache_for_current_db as _clear_graph_cache_for_current_db,
    list_graph_versions,
    load_graph,
    register_graph,
)
from tools.data.sqlite.db import connect_sqlite


__all__ = [
    "GraphActivationBlocked",
    "GraphVersionConflict",
    "activate_graph",
    "advance_graph_branch",
    "active_runtime_packet_budget_configuration",
    "authorize_graph_activation",
    "build_graph_branch_context",
    "build_graph_branch_next",
    "continue_graph_branch",
    "configure_runtime_packet_budget_profile",
    "create_graph_instance",
    "ensure_schema",
    "fork_graph_branch",
    "handoff_graph_branch",
    "list_graph_versions",
    "load_active_graph",
    "load_graph",
    "load_graph_branch",
    "load_current_graph_requirement",
    "load_research_cycle_object",
    "preview_graph_continuation",
    "record_audit",
    "record_proposal",
    "record_proposal_review",
    "record_validation",
    "register_graph",
    "revise_unused_draft",
    "rollback_active_graph",
]
