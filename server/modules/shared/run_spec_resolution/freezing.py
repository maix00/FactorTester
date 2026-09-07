"""Freeze configuration objects through one shared RunSpec input pipeline."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def freeze_run_spec_inputs(
    configuration: dict[str, Any], *, owner: str, analyses: list[str],
) -> dict[str, Any]:
    """Freeze every library-backed object required by selected analyses.

    Analysis modules declare references in their configuration.  This pipeline
    alone expands product scopes, external artifacts and the complete factor
    dependency graph before an immutable RunSpec is constructed.
    """
    from server.services.frozen_product_scope import freeze_product_scope
    from server.services import external_factor_artifacts, factor_revisions

    frozen = freeze_product_scope(
        configuration, owner=owner, analyses=analyses,
    )
    frozen = deepcopy(frozen)
    shared = frozen["payload"]["shared"]
    artifacts = external_factor_artifacts.freeze_configured_artifacts(shared)
    if artifacts:
        shared["external_factor_artifacts"] = artifacts
    return factor_revisions.freeze_factor_revisions(frozen, owner=owner)

