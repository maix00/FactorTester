from base64 import urlsafe_b64encode
import hashlib
import json

import pytest

from server.services.factor_subject_descriptors import (
    assert_factor_sets_match_run,
    compact_factor_subject_descriptors,
    validate_factor_subject_descriptors,
)


def _encode(value: str) -> str:
    return urlsafe_b64encode(value.encode()).decode().rstrip("=")


def _descriptor(alias: str = "F|N:20d") -> dict:
    member = (
        "factor:v1:profile-maxa:"
        f"{_encode('custom_factors/F.py')}:{_encode(alias)}:"
        + "a" * 40 + ":" + "b" * 40
    )
    members = [member]
    manifest = {
        "schema_version": 1,
        "set_id": "momentum",
        "set_ref": "factor-set:profile-maxa:momentum",
        "title_zh": "动量集合",
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


def test_descriptor_binds_manifest_to_git_blob_and_run_alias_hash() -> None:
    values = validate_factor_subject_descriptors([_descriptor()])
    assert values[0]["member_count"] == 1
    assert_factor_sets_match_run(
        values,
        factor_alias_hashes={hashlib.sha256(b"F|N:20d").hexdigest()},
    )
    assert compact_factor_subject_descriptors(values) == [{
        "target_ref": _descriptor()["target_ref"],
        "set_ref": "factor-set:profile-maxa:momentum",
        "member_hash": _descriptor()["manifest"]["member_hash"],
        "member_count": 1,
        "authority": "client_git_blob",
    }]


def test_descriptor_rejects_factor_set_not_executed_by_run() -> None:
    values = validate_factor_subject_descriptors([_descriptor()])
    with pytest.raises(ValueError, match="exactly match"):
        assert_factor_sets_match_run(
            values,
            factor_alias_hashes={hashlib.sha256(b"F|N:10d").hexdigest()},
        )
