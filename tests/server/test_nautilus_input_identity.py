from dataclasses import replace

import pytest

from server.services.nautilus_bridge.input_identity import freeze_bundle_input
from sources.registry import installed_bundles


def test_frozen_bundle_input_is_stable_and_compact():
    bundle = installed_bundles()[0]
    first = freeze_bundle_input(
        bundle, member_ids=("LocalCNFuturesContractMIN1",),
        authority="platform", owner="system", device="server-1",
        mapping_version="mapping-v1",
    )
    second = freeze_bundle_input(
        bundle, member_ids=("LocalCNFuturesContractMIN1",),
        authority="platform", owner="system", device="server-1",
        mapping_version="mapping-v1",
    )
    assert first == second
    assert first.input_ref == second.input_ref
    assert first.as_dict()["bundle_id"] == bundle.bundle_id
    assert "FieldHistory:market_rules:exchange" in first.related_members


def test_frozen_bundle_input_distinguishes_owner_device_and_mapping():
    bundle = installed_bundles()[0]
    base = dict(
        member_ids=("LocalCNFuturesContractMIN1",), authority="platform",
        owner="system", device="server-1", mapping_version="mapping-v1",
    )
    first = freeze_bundle_input(bundle, **base)
    assert first.input_ref != freeze_bundle_input(bundle, **{**base, "owner": "alice"}).input_ref
    assert first.input_ref != freeze_bundle_input(bundle, **{**base, "device": "server-2"}).input_ref
    assert first.input_ref != freeze_bundle_input(bundle, **{**base, "mapping_version": "mapping-v2"}).input_ref
    assert first.input_ref != freeze_bundle_input(
        replace(bundle, version="changed"), **base,
    ).input_ref


def test_frozen_bundle_input_rejects_foreign_member():
    bundle = installed_bundles()[0]
    with pytest.raises(ValueError, match="not in Bundle"):
        freeze_bundle_input(
            bundle, member_ids=("not-installed",), authority="platform",
            owner="system", device="server-1", mapping_version="mapping-v1",
        )
