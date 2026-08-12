from server.modules.shared import factor_param_resolver


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
