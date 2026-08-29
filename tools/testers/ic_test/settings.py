"""IC-test manifest composition."""

from __future__ import annotations

from tools.testers.ic_test.analysis_graph import (
    ic_analysis_graph_definition,
    ic_configuration_group_schema,
)
from tools.testers.ic_test.registration import (
    register_analysis_fields,
    register_authoring_shell,
    register_core_fields,
    register_result_contracts,
)
from tools.testers.settings.registry import ApplicationSettings


def register_ic_test_settings(app: ApplicationSettings) -> None:
    """Compose the IC manifest from domain-owned registration slices."""
    app.register_manifest_extension(
        "analysis_graph", ic_analysis_graph_definition().to_dict(),
    )
    app.register_manifest_extension("configuration_item_contract", {
        "schema_version": 1,
        "item_kind": "configuration-group",
        "collection_key": "configuration_groups",
        "min_items": 1,
        "max_items": 1,
        "schema": ic_configuration_group_schema(),
    })
    register_authoring_shell(app)
    register_core_fields(app)
    register_analysis_fields(app)
    register_result_contracts(app)
