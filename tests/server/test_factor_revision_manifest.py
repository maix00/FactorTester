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


def test_child_factor_uses_its_source_owner_for_revision_freeze(
    monkeypatch,
) -> None:
    calls: list[tuple[str, tuple[str, ...], str]] = []

    def definition(*, family_ref: str, factor_aliases: list[str], owner: str):
        calls.append((family_ref, tuple(factor_aliases), owner))
        return {
            **_definition(),
            "canonical_family_ref": family_ref,
            "resolved_factors": [{
                "factor_alias": alias,
                "tree_repr": alias,
                "column_refs": [],
            } for alias in factor_aliases],
        }

    monkeypatch.setattr(factor_revisions, "_load_revision_definition", definition)
    shared = {
        "factor_families": [{"alias": "CA"}],
        "factors": [{
            "alias": "CA|$F:1m",
            "factor_family_alias": "CA",
            "factor_family_ref": "CA",
            "factor_owner_ref": "GTHT@MaxJJW@392452984564",
        }],
    }

    factor_revisions.build_factor_revision_manifests(
        shared=shared,
        owner="GTHT@testA@545963541963",
    )

    assert calls == [(
        "GTHT@MaxJJW@392452984564:CA",
        ("CA|$F:1m",),
        "GTHT@testA@545963541963",
    )]


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
        "run_spec_version": 3,
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


def test_run_scoped_role_factor_is_frozen_without_registering_it_shared(
    monkeypatch,
) -> None:
    calls: list[tuple[str, tuple[str, ...]]] = []
    source = {"profile": "private profile source"}

    def definition(*, family_ref: str, factor_aliases: list[str], **_kwargs):
        calls.append((family_ref, tuple(factor_aliases)))
        is_profile = family_ref == "ProfileScreen"
        return {
            "canonical_family_ref": (
                "alice:ProfileScreen" if is_profile
                else "alice:ConditionalAlpha"
            ),
            "source_kind": "custom",
            "source_mode": "transient_run_source" if is_profile else "owner_only",
            "source_code": source["profile"] if is_profile else "shared source",
            "family_tree_repr": family_ref,
            "parameter_schema": [],
            "resolved_factors": [{
                "factor_alias": alias,
                "tree_repr": alias,
                "column_refs": [],
            } for alias in factor_aliases] or [{
                "factor_alias": "",
                "tree_repr": family_ref,
                "column_refs": [],
            }],
        }

    monkeypatch.setattr(factor_revisions, "_load_revision_definition", definition)
    configuration = _configuration()
    configuration["payload"]["shared"]["factors"].append({
        "factor_ref": "factor:profile-screen",
        "factor_family_alias": "ProfileScreen",
        "alias": "ProfileScreen|N:20d",
    })
    configuration["payload"]["analyses"]["backtest"] = {
        "groups": [{
            "id": "A1",
            "factorRoleBindings": {
                "screen": "factor:profile-screen",
            },
        }],
    }

    frozen = factor_revisions.freeze_factor_revisions(configuration, owner="alice")
    shared = frozen["payload"]["shared"]
    assert shared["factors"] == configuration["payload"]["shared"]["factors"]
    assert "factor_families" not in shared
    assert ("ProfileScreen", ("ProfileScreen|N:20d",)) in calls
    manifests = shared["factor_revision_manifests"]
    assert len(manifests) == 2
    assert all("private profile source" not in json.dumps(item) for item in manifests)

    run_spec = {"run_spec_version": 3, "configuration": frozen["payload"]}
    factor_revisions.assert_run_spec_factor_revisions_current(run_spec, owner="alice")
    source["profile"] = "changed transient source"
    with pytest.raises(ValueError, match="factor revision changed"):
        factor_revisions.assert_run_spec_factor_revisions_current(run_spec, owner="alice")


def test_column_ref_projection_does_not_invalidate_historical_run_spec(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        factor_revisions,
        "_load_revision_definition",
        lambda **_kwargs: _definition(),
    )
    frozen = factor_revisions.freeze_factor_revisions(
        _configuration(), owner="alice"
    )
    for manifest in frozen["payload"]["shared"]["factor_revision_manifests"]:
        manifest.pop("column_refs", None)

    factor_revisions.assert_run_spec_factor_revisions_current(
        {"run_spec_version": 3, "configuration": frozen["payload"]},
        owner="alice",
    )


def test_run_spec_v2_requires_manifests() -> None:
    with pytest.raises(ValueError, match="factor_revision_manifests"):
        factor_revisions.assert_run_spec_factor_revisions_current(
            {
                "run_spec_version": 3,
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
            "run_spec_version": 3,
            "configuration": frozen["payload"],
        },
    }
    build_execution_plan("test", payload)
    current["source_code"] = "changed before worker planning"

    with pytest.raises(ValueError, match="factor revision changed"):
        build_execution_plan("test", payload)
