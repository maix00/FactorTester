from server.modules.custom_factors import catalog


def test_custom_factor_catalog_reads_only_owner_metadata_without_user_tree(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "tools.data.sqlite.factor_metadata.list_factor_summaries",
        lambda kind, owner=None: calls.append((kind, owner)) or [{
            "id": "Momentum", "name": "Momentum",
            "family_formula_fingerprint": "a" * 64,
        }],
    )

    assert catalog.list_custom_factors("alice") == [{
        "id": "Momentum", "name": "Momentum",
        "family_formula_fingerprint": "a" * 64,
    }]
    assert calls == [("custom", "alice")]
    assert not hasattr(catalog, "list_visible_custom_factors")
