import pytest

from server.modules.shared import factor_param_resolver
from server.services import factor_registry
from server.services.factor_source_catalog import FactorSourceCatalog
from server.services import transient_factor_sources
from server.modules.shared.factor_param_utils import (
    factor_param_value_storage,
    normalize_factor_param_row,
)
from tools.factors.formula_identity import freeze_factor_identity


def _source(value: int) -> str:
    return f'''from tools.factors import FactorFamily
from tools.data.types import DataColumn
from tools.factors.FactorExpr import ColumnRef

class VersionProbe(FactorFamily):
    @staticmethod
    def factor_expr():
        return ColumnRef(DataColumn.CLOSE) + {value}
'''


def _frozen_probe(source: str) -> dict:
    factor_cls, _ = factor_param_resolver._load_factor_family_from_source(
        source, "VersionProbe",
    )
    assert factor_cls is not None
    family = factor_cls()
    normalized = normalize_factor_param_row(family, {})
    factor = family.get_factor(**normalized)
    expression = getattr(factor, "_source_expr", None) or factor.expr
    return freeze_factor_identity(
        owner_ref="principal:alice",
        family_alias="VersionProbe",
        factor_alias=str(factor.alias),
        family_formula_fingerprint=family.expr.semantic_fingerprint(),
        self_formula_fingerprint=expression.semantic_fingerprint(),
        params={
            parameter.alias: factor_param_value_storage(
                parameter, normalized.get(parameter.alias),
            )
            for parameter in family.params
        },
    )


def test_find_visible_factor_uses_factor_library_overview(monkeypatch) -> None:
    monkeypatch.setattr(factor_param_resolver, "current_user", lambda: "alice")
    monkeypatch.setattr(
        factor_param_resolver,
        "build_factor_library_overview",
        lambda username, include_subordinates: {
            "factors": [{"factor_alias": "PxVWAP|$F:1m"}]
        },
    )

    assert factor_param_resolver._find_visible_factor("PxVWAP") == {
        "factor_alias": "PxVWAP|$F:1m"
    }


def test_find_visible_factor_accepts_explicit_worker_owner(monkeypatch) -> None:
    monkeypatch.setattr(
        factor_param_resolver,
        "current_user",
        lambda: (_ for _ in ()).throw(AssertionError("request context must not be used")),
    )
    seen = []
    monkeypatch.setattr(
        factor_param_resolver,
        "build_factor_library_overview",
        lambda username, include_subordinates: (
            seen.append((username, include_subordinates))
            or {"factors": [{"factor_alias": "PxVWAP|$F:1m"}]}
        ),
    )

    assert factor_param_resolver._find_visible_factor(
        "PxVWAP", username="worker-owner"
    )["factor_alias"] == "PxVWAP|$F:1m"
    assert seen == [("worker-owner", True)]


def test_frozen_factor_uses_exact_history_when_current_catalog_moved(
    monkeypatch,
) -> None:
    old_source = _source(1)
    new_source = _source(2)
    frozen = _frozen_probe(old_source)
    calls = []

    def version(_self, principal, source_kind, family_alias, fingerprint, *, owner_username=""):
        calls.append((principal, source_kind, family_alias, fingerprint, owner_username))
        if fingerprint == "current":
            return {"source_code": new_source}
        if fingerprint == frozen["identity"]["family_formula_fingerprint"]:
            return {"source_code": old_source}
        raise FileNotFoundError(fingerprint)

    monkeypatch.setattr(FactorSourceCatalog, "version", version)
    resolved = factor_param_resolver._resolve_frozen_factor(
        frozen, username="alice", frozen_by_ref={frozen["ref"]: frozen},
    )

    resolved_expression = getattr(resolved, "_source_expr", None) or resolved.expr
    assert resolved_expression.semantic_fingerprint() == frozen["identity"]["self_formula_fingerprint"]
    assert [call[3] for call in calls] == [
        "current", frozen["identity"]["family_formula_fingerprint"],
    ]


def test_transient_scope_source_is_authoritative_and_checked(monkeypatch) -> None:
    source = _source(1)
    frozen = _frozen_probe(source)
    monkeypatch.setattr(
        FactorSourceCatalog, "version",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("run-scoped factors must not consult the mutable catalog")
        ),
    )

    with factor_registry.transient_factor_source_scope(
        owner="alice", overrides={"VersionProbe": source},
    ):
        resolved = factor_param_resolver._resolve_frozen_factor(
            frozen, username="alice", frozen_by_ref={frozen["ref"]: frozen},
        )

    resolved_expression = getattr(resolved, "_source_expr", None) or resolved.expr
    assert resolved_expression.semantic_fingerprint() == frozen["identity"]["self_formula_fingerprint"]


def test_required_run_source_fails_closed_instead_of_using_catalog(
    monkeypatch,
) -> None:
    frozen = _frozen_probe(_source(1))
    monkeypatch.setattr(
        FactorSourceCatalog, "version",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("required source cannot fall back to catalog")
        ),
    )

    with factor_registry.required_run_factor_sources({"alice:VersionProbe"}):
        with pytest.raises(ValueError, match="retained factor source is unavailable"):
            factor_param_resolver._resolve_frozen_factor(
                frozen, username="alice", frozen_by_ref={frozen["ref"]: frozen},
            )


def test_run_spec_uses_hash_checked_retained_profile_source(
    monkeypatch, tmp_path,
) -> None:
    source = _source(1)
    frozen = _frozen_probe(source)
    monkeypatch.setattr(
        transient_factor_sources.Settings,
        "CACHE_DB_PATH",
        str(tmp_path / "cache.sqlite"),
    )
    scope = transient_factor_sources.create_scope(
        owner="alice",
        entries=[{
            "path": "custom_factors/VersionProbe.py",
            "source_code": source,
        }],
    )
    policy = {"mode": "transient_run_source", "files": scope["files"]}
    monkeypatch.setattr(
        FactorSourceCatalog, "version",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("retained profile sources must not use catalog fallback")
        ),
    )

    try:
        with factor_registry.transient_factor_source_scope(
            scope["scope_id"], owner="alice",
        ):
            with factor_registry.run_factor_source_policy_scope(
                {"factor_source_policy": policy}, owner="alice",
            ):
                resolved = factor_param_resolver._resolve_frozen_factor(
                    frozen, username="alice", frozen_by_ref={frozen["ref"]: frozen},
                )
    finally:
        transient_factor_sources.cleanup_scope(scope["scope_id"])

    resolved_expression = getattr(resolved, "_source_expr", None) or resolved.expr
    assert resolved_expression.semantic_fingerprint() == frozen["identity"]["self_formula_fingerprint"]


def test_corrupt_retained_profile_source_does_not_fall_back_to_catalog(
    monkeypatch, tmp_path,
) -> None:
    source = _source(1)
    frozen = _frozen_probe(source)
    monkeypatch.setattr(
        transient_factor_sources.Settings,
        "CACHE_DB_PATH",
        str(tmp_path / "cache.sqlite"),
    )
    scope = transient_factor_sources.create_scope(
        owner="alice",
        entries=[{
            "path": "custom_factors/VersionProbe.py",
            "source_code": source,
        }],
    )
    source_path = (
        tmp_path / "transient_factor_sources" / scope["scope_id"]
        / "custom_factors" / "VersionProbe.py"
    )
    source_path.write_text(_source(2), encoding="utf-8")
    policy = {"mode": "transient_run_source", "files": scope["files"]}
    monkeypatch.setattr(
        FactorSourceCatalog, "version",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("a corrupt retained source must not fall back")
        ),
    )

    try:
        with factor_registry.transient_factor_source_scope(
            scope["scope_id"], owner="alice",
        ):
            with factor_registry.run_factor_source_policy_scope(
                {"factor_source_policy": policy}, owner="alice",
            ):
                with pytest.raises(ValueError, match="failed owner/hash validation"):
                    factor_param_resolver._resolve_frozen_factor(
                        frozen, username="alice", frozen_by_ref={frozen["ref"]: frozen},
                    )
    finally:
        transient_factor_sources.cleanup_scope(scope["scope_id"])


def test_inline_transient_factor_resolves_from_embedded_source(monkeypatch) -> None:
    source = _source(1)
    frozen = {
        **_frozen_probe(source),
        "temporary": True,
        "source_kind": "transient",
        "source_origin": "test_inline",
        "source_code": source,
    }
    monkeypatch.setattr(
        FactorSourceCatalog, "version",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("inline factors must resolve from their embedded source")
        ),
    )

    resolved = factor_param_resolver._resolve_frozen_factor(
        frozen, username="alice", frozen_by_ref={frozen["ref"]: frozen},
    )

    resolved_expression = getattr(resolved, "_source_expr", None) or resolved.expr
    assert resolved_expression.semantic_fingerprint() == frozen["identity"]["self_formula_fingerprint"]
