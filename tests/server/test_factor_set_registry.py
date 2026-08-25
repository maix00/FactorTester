from server.modules.custom_factors import factor_set_registry as registry
from tools.factors.factor_set_identity import freeze_factor_set_identity
from tools.factors.formula_identity import freeze_factor_identity


def _descriptor() -> dict:
    member = freeze_factor_identity(
        owner_ref="profile:maxa",
        family_alias="F",
        factor_alias="F|N:20d",
        family_formula_fingerprint="a" * 64,
        self_formula_fingerprint="b" * 64,
        params={"N": "20d"},
    )
    manifest = freeze_factor_set_identity(
        owner_ref="profile:maxa",
        set_id="momentum",
        alias="动量集合",
        members=[member],
    )
    manifest["description"] = "服务器可检索版本"
    return {
        "target_ref": manifest["ref"],
        "manifest": manifest,
    }


def test_registered_factor_set_is_server_owned_and_member_paged(monkeypatch) -> None:
    stored = {}
    monkeypatch.setattr(
        registry, "save_factor_set",
        lambda username, value: stored.setdefault(username, dict(value)),
    )
    monkeypatch.setattr(
        registry, "list_factor_sets",
        lambda username: [stored[username]],
    )
    monkeypatch.setattr(
        registry, "get_factor_set",
        lambda username, _target_ref: stored.get(username),
    )

    saved = registry.register_factor_set("alice", _descriptor())
    assert saved["owner_username"] == "alice"
    assert saved["owner_ref"] == "profile:maxa"
    assert registry.factor_set_catalog("alice", "动量")[0]["member_count"] == 1

    detail = registry.factor_set_detail(
        "alice", saved["target_ref"], offset=0, limit=1,
    )
    assert detail is not None
    assert detail["has_more"] is False
    assert detail["related_references"][0]["label"] == "F|N:20d"
    assert detail["related_references"][0]["target_ref"].startswith("factor:v2:")
    assert registry.factor_set_descriptor("alice", saved["target_ref"]) == _descriptor()


def test_unregistered_factor_set_is_not_visible(monkeypatch) -> None:
    monkeypatch.setattr(registry, "get_factor_set", lambda *_args: None)
    assert registry.factor_set_detail(
        "alice", "factor-set:v2:" + "x" * 43, offset=0, limit=10,
    ) is None
    assert registry.factor_set_descriptor(
        "alice", "factor-set:v2:" + "x" * 43,
    ) is None


def test_web_authored_factor_set_uses_current_principal_owner(monkeypatch) -> None:
    descriptor = _descriptor()
    member = descriptor["manifest"]["identity"]["members"][0]
    stored = []
    monkeypatch.setattr(
        registry, "save_factor_set",
        lambda username, value: stored.append((username, value)) or value,
    )

    value = registry.author_factor_set(
        "GTHT@alice@1",
        {
            "set_id": "momentum",
            "alias": "动量集合",
            "description": "Web 创建",
            "members": [member],
        },
        persist=True,
    )

    assert stored[0][0] == "GTHT@alice@1"
    assert stored[0][1]["owner_ref"] == "principal:GTHT@alice@1"
    assert value["owner_ref"] == "principal:GTHT@alice@1"
    assert value["can_edit"] is True
    assert value["manifest"]["identity"]["members"] == [member]


def test_inline_factor_set_is_frozen_without_persistence(monkeypatch) -> None:
    descriptor = _descriptor()
    member = descriptor["manifest"]["identity"]["members"][0]
    monkeypatch.setattr(
        registry, "save_factor_set",
        lambda *_args: (_ for _ in ()).throw(AssertionError("must not persist")),
    )

    value = registry.author_factor_set(
        "alice",
        {"set_id": "inline", "alias": "现场集合", "members": [member]},
        persist=False,
    )

    assert value["temporary"] is True
    assert value["owner_ref"] == "principal:alice"
    assert value["manifest"]["ref"] == value["target_ref"]
