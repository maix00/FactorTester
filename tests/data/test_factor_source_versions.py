from __future__ import annotations

import pytest

import settings as Settings
from tools.data.sqlite import factor_source_versions


def _fingerprint(character: str) -> str:
    return character * 64

def test_formula_versions_roundtrip_without_git_identity(monkeypatch, tmp_path):
    database = tmp_path / "factor-source-versions.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", database)
    source = "class Momentum(FactorFamily):\n    pass\n"

    saved = factor_source_versions.record_factor_formula_version(
        "public",
        "ignored-owner",
        "Momentum",
        source,
        family_formula_fingerprint=_fingerprint("a"),
        subject="create",
    )

    listed = factor_source_versions.list_factor_formula_versions(
        "public", "", "Momentum"
    )
    assert [item["family_formula_fingerprint"] for item in listed] == [
        _fingerprint("a")
    ]
    assert not ({"commit", "revision", "git_commit_sha"} & set(listed[0]))

    loaded = factor_source_versions.load_factor_formula_version(
        "public", "another-owner", "Momentum", _fingerprint("a")
    )
    assert loaded is not None
    assert loaded["source_code"] == source
    assert loaded["source_sha256"] == saved["source_sha256"]


def test_formula_version_deduplicates_source_changes_with_same_formula(
    monkeypatch, tmp_path
):
    database = tmp_path / "factor-source-versions.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", database)
    first = "class Momentum(FactorFamily):\n    pass\n"
    later = "# prose-only change\nclass Momentum(FactorFamily):\n    pass\n"
    fingerprint = _fingerprint("b")

    factor_source_versions.record_factor_formula_version(
        "public",
        "",
        "Momentum",
        first,
        family_formula_fingerprint=fingerprint,
    )
    factor_source_versions.record_factor_formula_version(
        "public",
        "",
        "Momentum",
        later,
        family_formula_fingerprint=fingerprint,
    )

    loaded = factor_source_versions.load_factor_formula_version(
        "public", "", "Momentum", fingerprint
    )
    assert loaded is not None
    assert loaded["source_code"] == first


def test_custom_formula_version_keeps_owner_scope(monkeypatch, tmp_path):
    database = tmp_path / "factor-source-versions.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", database)
    source = "class Momentum(FactorFamily):\n    pass\n"
    fingerprint = _fingerprint("c")

    factor_source_versions.record_factor_formula_version(
        "custom",
        "alice",
        "Momentum",
        source,
        family_formula_fingerprint=fingerprint,
    )

    assert (
        factor_source_versions.load_factor_formula_version(
            "custom", "bob", "Momentum", fingerprint
        )
        is None
    )
    assert factor_source_versions.load_factor_formula_version(
        "custom", "alice", "Momentum", fingerprint
    )["source_code"] == source


def test_formula_version_requires_full_semantic_fingerprint(monkeypatch, tmp_path):
    database = tmp_path / "factor-source-versions.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", database)

    with pytest.raises(ValueError, match="formula fingerprint"):
        factor_source_versions.record_factor_formula_version(
            "custom",
            "alice",
            "Momentum",
            "class Momentum(FactorFamily):\n    pass\n",
            family_formula_fingerprint="short",
        )


def test_upsert_factor_source_enqueues_fingerprint_into_outbox(monkeypatch, tmp_path):
    """Saving a factor source must put its family_formula_fingerprint into the
    factor_source outbox payload, so a receiving server can converge version
    history (source body is still pulled lazily on demand).

    This is the source-end half of the cross-server version-sync chain that
    keeps factor_family_formula_versions consistent across servers.
    """
    database = tmp_path / "factor-source.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", database)
    fingerprint = _fingerprint("c")

    import tools.data.sqlite.factor_source_store as store

    store.upsert_factor_source(
        "custom",
        "alice",
        "Momentum",
        "Momentum",
        "class Momentum(FactorFamily):\n    pass\n",
        family_formula_fingerprint=fingerprint,
    )

    # The enqueued factor_source row is held in the local outbox as an
    # account-domain entity.  Read it back and confirm the fingerprint travelled
    # with the payload.
    from server.manager.storage.account_domain.local import LocalAccountDomainStore

    local = LocalAccountDomainStore(str(database))
    pending = local.pending(principal="alice", limit=1000)
    rows = [item for item in pending if item["entity_type"] == "factor_source"]
    assert rows, "expected a pending factor_source outbox row after upsert"
    payload = rows[0]["payload"]
    assert payload["factor_id"] == "Momentum"
    assert payload["family_formula_fingerprint"] == fingerprint, (
        "factor_source outbox payload must carry family_formula_fingerprint so "
        "the receiving server can record version history"
    )
    # storage_server_id is set from FACTORTESTER_SERVER_ID and is empty in a
    # bare test run; the fingerprint (the cross-server convergence key) is what
    # matters here, not the origin label.
    assert "source_sha256" in payload
