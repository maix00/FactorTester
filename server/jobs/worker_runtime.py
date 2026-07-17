"""Initialize process-local runtime dependencies shared by planner and execution workers."""

from __future__ import annotations


def initialize_worker_runtime() -> None:
    # Import registers the server product-tree resolver on ProductPathSelection.
    from server.modules.shared import submission_helpers as _submission_helpers

    assert _submission_helpers.resolve_products_from_paths
