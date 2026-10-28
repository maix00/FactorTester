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


def test_catalog_plan_preserves_product_refs_without_source_or_product_imports():
    import subprocess
    import sys
    from pathlib import Path
    code = """
import sys
from server.services.nautilus_bridge.catalog_plan import catalog_staging_requests
path = 'Product/Futures/CNFutures/_products/AU.SHF'
spec = {'configuration':{'shared':{'product_selections':{'scope':{'paths':[path]}}},'analyses':{'backtest':{'groups':[{'id':'s','product_scope_ref':'scope'}]}}}}
assert catalog_staging_requests(spec)[0]['paths'] == [path]
assert not any(name == 'settings' or name.startswith(('sources.', 'tools.products.', 'nautilus_trader.')) for name in sys.modules)
"""
    subprocess.run([sys.executable, "-S", "-c", code], check=True,
                   capture_output=True, text=True, cwd=Path(__file__).resolve().parents[2])
