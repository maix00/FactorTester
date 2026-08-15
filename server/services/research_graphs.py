"""Stable public façade for Research Graph application services."""

from server.services.research_graph.active_pointer import (
    activate_graph,
    load_active_graph,
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
from server.services.research_graph.protocol import (
    GraphActivationBlocked,
    GraphVersionConflict,
)
from server.services.research_graph.schema import ensure_schema
from server.services.research_graph.presentation_contract import (
    DEFAULT_GRAPH_LOCALE,
    SUPPORTED_GRAPH_LOCALES,
    normalize_graph_locale,
    validate_presentation,
)
from server.services.research_graph.presentations import (
    attach_presentation,
    list_presentations,
    load_presentation,
    register_presentation,
)
from server.services.research_graph.user_graphs import (
    delete_graph as delete_user_graph,
    list_graphs as list_user_graphs,
    load_graph_file as load_user_graph,
    upload_graph as upload_user_graph,
)
from server.services.research_graph.user_graph_preferences import (
    get_default as get_default_user_graph,
    set_default as set_default_user_graph,
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
    "activate_graph",
    "advance_graph_branch",
    "build_graph_branch_context",
    "build_graph_branch_edge_info",
    "build_graph_branch_next",
    "continue_graph_branch",
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
    "load_current_graph_requirement",
    "load_research_cycle_object",
    "preview_graph_continuation",
    "register_graph",
    "register_presentation",
    "attach_presentation",
    "normalize_graph_locale",
    "validate_presentation",
    "delete_user_graph",
    "get_default_user_graph",
    "list_user_graphs",
    "load_user_graph",
    "set_default_user_graph",
    "upload_user_graph",
]
