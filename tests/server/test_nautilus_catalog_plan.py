from server.services.nautilus_bridge.catalog_plan import catalog_staging_requests


def test_catalog_plan_collects_frozen_paths():
    run_spec = {"configuration": {
        "shared": {"product_selections": {
            "scope-1": {"paths": ["CFFEX|F|T|2403", "CFFEX|F|T|2406"]},
        }},
        "analyses": {"backtest": {"groups": [
            {"id": "s1", "product_path_selection_id": "scope-1"},
            {"id": "s2", "product_path_selection_id": "scope-1"},
        ]}},
    }}
    assert catalog_staging_requests(run_spec) == [{
        "scope_ref": "scope-1",
        "paths": ["CFFEX|F|T|2403", "CFFEX|F|T|2406"],
        "strategy_ids": ["s1", "s2"],
    }]
