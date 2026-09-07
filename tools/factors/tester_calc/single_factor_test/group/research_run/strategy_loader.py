"""Compatibility import for shared RunSpec strategy reconstruction."""

def strategy_objects_from_payload(payload, *, aliases_by_index=None):
    from server.modules.shared.run_spec_resolution.strategies import (
        strategy_objects_from_run_spec,
    )

    return strategy_objects_from_run_spec(
        payload, aliases_by_index=aliases_by_index,
    )
