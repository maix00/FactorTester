"""Migrate saved template snapshots from legacy top-level ``params_list`` to
the ``parameters.params_list`` shape used by the Panels registry
(static/js/modules/single_factor_test/panel_registry.js).
"""

from __future__ import annotations

from typing import Any


def migrate_snapshot_params_list(snapshot: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Return (snapshot, changed) with legacy top-level params_list moved under parameters."""
    if not isinstance(snapshot, dict):
        return snapshot, False
    legacy = snapshot.get('params_list')
    if not isinstance(legacy, list):
        return snapshot, False
    migrated = dict(snapshot)
    del migrated['params_list']
    existing_parameters = migrated.get('parameters')
    if not isinstance(existing_parameters, dict) or not isinstance(existing_parameters.get('params_list'), list):
        migrated['parameters'] = {'params_list': legacy}
    return migrated, True
