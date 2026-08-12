from base64 import urlsafe_b64encode
import hashlib
import json

from server.modules.custom_factors import factor_set_registry as registry


def _encode(value: str) -> str:
    return urlsafe_b64encode(value.encode()).decode().rstrip("=")


def _descriptor() -> dict:
    member = (
        "factor:v1:profile-maxa:"
        f"{_encode('custom_factors/F.py')}:{_encode('F|N:20d')}:"
        + "a" * 40 + ":" + "b" * 40
    )
    members = [member]
    manifest = {
        "schema_version": 1,
        "set_id": "momentum",
        "set_ref": "factor-set:profile-maxa:momentum",
        "title_zh": "动量集合",
        "description_zh": "服务器可检索版本",
        "member_refs": members,
        "member_hash": "sha256:" + hashlib.sha256(json.dumps(
            members, ensure_ascii=False, separators=(",", ":"),
        ).encode()).hexdigest(),
    }
    payload = (
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode()
    blob = hashlib.sha1(
        f"blob {len(payload)}\0".encode() + payload
    ).hexdigest()
    return {
        "target_ref": (
            "factor-set:v1:profile-maxa:"
            f"{_encode('.factortester/factor-sets/momentum.json')}:"
            f"{_encode('momentum')}:" + "c" * 40 + f":{blob}"
        ),
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
    assert saved["set_ref"] == "factor-set:profile-maxa:momentum"
    assert registry.factor_set_catalog("alice", "动量")[0]["member_count"] == 1

    detail = registry.factor_set_detail(
        "alice", saved["target_ref"], offset=0, limit=1,
    )
    assert detail is not None
    assert detail["has_more"] is False
    assert detail["related_references"][0]["target_ref"].startswith("factor:v1:")


def test_unregistered_factor_set_is_not_visible(monkeypatch) -> None:
    monkeypatch.setattr(registry, "get_factor_set", lambda *_args: None)
    assert registry.factor_set_detail(
        "alice", "factor-set:v1:missing", offset=0, limit=10,
    ) is None
