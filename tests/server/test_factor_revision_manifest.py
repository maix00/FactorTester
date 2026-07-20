"""Source-free factor identities frozen into immutable RunSpecs."""

from __future__ import annotations

from copy import deepcopy
import json

import pytest

from server.modules.single_factor_test.planning import build_execution_plan
from server.services import factor_revisions


def _definition(*, source: str = "secret source") -> dict:
    return {
        "canonical_family_ref": "alice:ConditionalAlpha",
        "source_kind": "custom",
        "source_code": source,
        "family_tree_repr": "where(aux > 0, main, 0)",
        "parameter_schema": [{
            "alias": "AUX",
            "type": "FactorParam",
            "default_value": None,
        }],
        "resolved_factors": [{
            "factor_alias": "ConditionalAlpha|AUX:[Trend|N:20d]",
            "tree_repr": "where(rolling_mean(close,20) > 0, close, 0)",
        }],
    }


def _configuration() -> dict:
    return {
        "configuration_id": "configuration-1",
        "revision": 3,
        "fingerprint": "f" * 64,
        "payload": {
            "schema_version": 1,
            "shared": {
                "factor_families": [{"alias": "alice:ConditionalAlpha"}],
                "factors": [{
                    "factor_family_alias": "alice:ConditionalAlpha",
                    "alias": (
                        "ConditionalAlpha|AUX:[Trend|N:20d]"
                    ),
                }],
            },
            "analyses": {"ic": {}},
            "ui": {},
        },
    }


def test_manifest_is_source_free_and_changes_with_resolved_semantics(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        factor_revisions,
        "_load_revision_definition",
        lambda **_kwargs: _definition(),
    )

    first = factor_revisions.build_factor_revision_manifests(
        shared=_configuration()["payload"]["shared"],
        owner="alice",
    )
    repeated = factor_revisions.build_factor_revision_manifests(
        shared=_configuration()["payload"]["shared"],
        owner="alice",
    )
    changed_definition = _definition()
    changed_definition["resolved_factors"][0]["tree_repr"] += "+volume"
    monkeypatch.setattr(
        factor_revisions,
        "_load_revision_definition",
        lambda **_kwargs: changed_definition,
    )
    changed = factor_revisions.build_factor_revision_manifests(
        shared=_configuration()["payload"]["shared"],
        owner="alice",
    )

    assert first == repeated
    assert first != changed
    manifest = first[0]
    assert manifest["schema_version"] == 1
    assert manifest["factor_family_ref"] == "alice:ConditionalAlpha"
    assert manifest["source_access_policy"] == "owner_only"
    assert all(len(manifest[field]) == 64 for field in (
        "family_source_hash",
        "family_expr_hash",
        "parameter_schema_hash",
        "resolved_factor_expr_hash",
        "operator_registry_hash",
        "manifest_hash",
    ))
    serialized = json.dumps(first)
    assert "secret source" not in serialized
    assert "where(" not in serialized
    assert "rolling_mean" not in serialized
    assert "Trend|N:20d" not in serialized


def test_freeze_and_execution_revalidation_share_one_manifest_path(
    monkeypatch,
) -> None:
    current = _definition()
    monkeypatch.setattr(
        factor_revisions,
        "_load_revision_definition",
        lambda **_kwargs: deepcopy(current),
    )
    frozen = factor_revisions.freeze_factor_revisions(
        _configuration(),
        owner="alice",
    )
    run_spec = {
        "run_spec_version": 2,
        "configuration": frozen["payload"],
    }

    factor_revisions.assert_run_spec_factor_revisions_current(
        run_spec,
        owner="alice",
    )
    current["source_code"] = "changed after submission"

    with pytest.raises(ValueError, match="factor revision changed"):
        factor_revisions.assert_run_spec_factor_revisions_current(
            run_spec,
            owner="alice",
        )


def test_run_spec_v2_requires_manifests() -> None:
    with pytest.raises(ValueError, match="factor_revision_manifests"):
        factor_revisions.assert_run_spec_factor_revisions_current(
            {
                "run_spec_version": 2,
                "configuration": {
                    "shared": {
                        "factor_families": [{"alias": "MmRet"}],
                        "factors": [],
                    },
                },
            },
            owner="alice",
        )


def test_worker_planning_fails_after_factor_revision_changes(
    monkeypatch,
) -> None:
    current = _definition()
    monkeypatch.setattr(
        factor_revisions,
        "_load_revision_definition",
        lambda **_kwargs: deepcopy(current),
    )
    frozen = factor_revisions.freeze_factor_revisions(
        _configuration(),
        owner="alice",
    )
    payload = {
        "_owner": "alice",
        "run_spec": {
            "run_spec_version": 2,
            "configuration": frozen["payload"],
        },
    }
    build_execution_plan("test", payload)
    current["source_code"] = "changed before worker planning"

    with pytest.raises(ValueError, match="factor revision changed"):
        build_execution_plan("test", payload)
