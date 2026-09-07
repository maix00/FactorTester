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
        "create_template": {
            "config_group_id": "<unique-configuration-group-id>",
            "batch_id": "<unique-batch-id>",
            "name": "<configuration-group-name>",
            "factor_ref": "<factor-ref>",
            "product_scope_ref": "<product-group-ref>",
            "entry_delay_bars": 0,
            "horizon": {"sampling": "scale_aware"},
            "methods": ["rank"],
            "return_price_basis": "next_open_to_open_adjusted",
            "warmup_mode": "auto",
            "warmup_window": "30d",
            "analysis_attachments": [],
            "editor_mounted_tabs": [
                "__configuration__", "factor", "product_path_selection",
            ],
        },
        "field_sources": {
            "factor_ref": "field:factor_candidates",
            "product_scope_ref": "field:product_path_selection",
        },
        "owned_tabs": ["return_frequency", "delay", "ic_method"],
        "schema": ic_configuration_group_schema(),
    })
    register_authoring_shell(app)
    register_core_fields(app)
    register_analysis_fields(app)
    register_result_contracts(app)
