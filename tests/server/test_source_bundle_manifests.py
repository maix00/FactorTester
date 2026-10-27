"""Installed source discovery must be source-free and preserve runtime feeds."""
from copy import deepcopy
import importlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from traderesearch_data.bundles import discover_bundle_manifests, parse_bundle_manifest

ROOT = Path(__file__).resolve().parents[2]


def example():
    return json.loads((ROOT / "sources/Local/bundle.json").read_text())


def write_manifest(root, value, name="example"):
    directory = root / name
    directory.mkdir()
    (directory / "bundle.json").write_text(json.dumps(value))


def test_json_inventory_does_not_import_sources_or_nautilus(tmp_path, monkeypatch):
    value = example()
    value["entrypoints"] = ["never.import.this_plugin"]
    value["members"][0]["integrations"] = {"nautilus": "never.import.adapter:load"}
    write_manifest(tmp_path, value)
    monkeypatch.setattr(importlib, "import_module", lambda *a, **k: pytest.fail("metadata imported code"))
    manifests = discover_bundle_manifests(tmp_path)
    assert manifests[0].members[0].integrations == (("nautilus", "never.import.adapter:load"),)
    assert manifests[0].members[-1].kind == "historical_rules"
    assert manifests[0].members[-1].frequency is None
    completed = subprocess.run([sys.executable, "-S", "-c", "from sources.registry import installed_bundles; import sys; assert installed_bundles(); assert not any(k.startswith(('nautilus_trader', 'tools.data', 'server.', 'sources.LocalCNFutures')) for k in sys.modules)"], cwd=ROOT, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr


def test_product_identity_is_not_a_provider_path_or_category(tmp_path):
    value = example()
    first, second = value["members"][:2]
    value["product_bindings"] = [
        {"product_ref": "product:gold", "member_id": first["id"], "source_product_ref": "AU.SHF"},
        {"product_ref": "product:gold", "member_id": second["id"], "source_product_ref": "SHFE:AU"},
    ]
    bundle = parse_bundle_manifest(value)
    assert bundle.product_bindings[0].product_ref == bundle.product_bindings[1].product_ref
    assert bundle.product_bindings[0].source_product_ref != bundle.product_bindings[1].source_product_ref
    value["product_bindings"].append(deepcopy(value["product_bindings"][0]))
    with pytest.raises(ValueError, match="duplicate"):
        parse_bundle_manifest(value)


@pytest.mark.parametrize("change", [
    lambda x: x.update(schema_version=True),
    lambda x: x["members"].append(deepcopy(x["members"][0])),
    lambda x: x["members"][0].update(related_members=["missing"]),
    lambda x: x["members"][-1].update(frequency="MIN1"),
    lambda x: x["members"][0].update(kind="unknown"),
    lambda x: x["members"][0]["update_policy"].update(mode="immutable_snapshot"),
    lambda x: x["members"][0]["update_policy"].update(mode="live_stream", replay_policy="frozen_input"),
    lambda x: x["members"][0]["update_policy"].update(max_staleness_seconds=-1),
])
def test_invalid_metadata_fails_without_silent_fallback(change):
    value = example()
    change(value)
    with pytest.raises(ValueError):
        parse_bundle_manifest(value)


def test_unversioned_live_source_does_not_claim_replay():
    value = example()
    value["members"][0]["update_policy"].update(mode="live_stream", replay_policy="not_declared")
    result = parse_bundle_manifest(value).members[0].update_policy
    assert result.mode == "live_stream"
    assert result.replay_policy == "not_declared"


def test_inventory_rejects_duplicate_ids_keys_and_escaping_metadata(tmp_path):
    write_manifest(tmp_path, example(), "one")
    write_manifest(tmp_path, example(), "two")
    with pytest.raises(ValueError, match="duplicate installed"):
        discover_bundle_manifests(tmp_path)
    (tmp_path / "two/bundle.json").unlink()
    (tmp_path / "one/bundle.json").write_text('{"schema_version":1,"schema_version":1}')
    with pytest.raises(ValueError, match="duplicate JSON"):
        discover_bundle_manifests(tmp_path)


def test_warm_snapshot_avoids_directory_reads_and_client_activation(monkeypatch):
    import sources.registry as registry
    first = registry.installed_bundles(refresh=True)
    modules = registry.iter_source_modules()
    monkeypatch.setattr(registry, "discover_bundle_manifests", lambda *_: pytest.fail("warm inventory reread"))
    assert registry.installed_bundles() is first
    assert registry.iter_source_modules() is modules
    client = deepcopy(example())
    client.update(bundle_id="client-only", execution_location="client", provisioner="user", entrypoints=["never.import.client"])
    manifest = parse_bundle_manifest(client)
    monkeypatch.setattr(registry, "discover_bundle_manifests", lambda *_: (*first, manifest))
    try:
        assert registry.installed_bundles(refresh=True)[-1] is manifest
        assert "never.import.client" not in registry.iter_source_modules()
    finally:
        registry._INVENTORY = first
        registry._MODULES = modules


def test_existing_four_market_feeds_are_explicit_not_prefix_selected():
    from sources.registry import load_all_sources
    load_all_sources()
    from sources.Local.data_source_bundle import LOCAL
    assert {source.key for source in LOCAL.members} == {
        "LocalCNFuturesMIN1", "LocalCNFuturesDAY1", "LocalCNFuturesContractMIN1", "LocalCNFuturesContractDAY1",
    }


def test_refresh_failure_preserves_last_valid_inventory(monkeypatch):
    import sources.registry as registry
    before = registry.installed_bundles()
    def broken(*_):
        raise ValueError("invalid installed manifest")
    monkeypatch.setattr(registry, "discover_bundle_manifests", broken)
    with pytest.raises(ValueError, match="invalid installed"):
        registry.installed_bundles(refresh=True)
    assert registry.installed_bundles() is before


def test_unrelated_local_provider_is_not_silently_joined(monkeypatch):
    from types import SimpleNamespace
    from sources.registry import load_all_sources
    load_all_sources()
    from sources.Local.data_source_bundle import LOCAL
    from tools.data.providers.DataProviderProductTS import DataProviderProductTS
    original = tuple(DataProviderProductTS.all())
    monkeypatch.setattr(DataProviderProductTS, "all", classmethod(lambda cls: (*original, SimpleNamespace(key="LocalUnrelated"))))
    assert "LocalUnrelated" not in {source.key for source in LOCAL.members}


def test_manifest_bytes_and_symlink_boundaries_are_enforced(tmp_path):
    from traderesearch_data.bundles import MAX_MANIFEST_BYTES
    write_manifest(tmp_path, example())
    path = tmp_path / "example/bundle.json"
    path.write_bytes(b" " * (MAX_MANIFEST_BYTES + 1))
    with pytest.raises(ValueError, match="size limit"):
        discover_bundle_manifests(tmp_path)
    path.unlink()
    external = tmp_path.parent / (tmp_path.name + "-outside.json")
    external.write_text(json.dumps(example()))
    try:
        path.symlink_to(external)
        with pytest.raises(ValueError, match="escapes"):
            discover_bundle_manifests(tmp_path)
    finally:
        external.unlink()


def test_docker_bundle_overlay_is_explicit_read_only_and_never_creates_roots():
    import yaml
    for name, service in (("factortester-server", "manager"), ("factortester-public", "factortester-public")):
        path = ROOT / "deploy/docker" / name / "compose.bundles.yaml"
        config = yaml.safe_load(path.read_text())["services"][service]
        assert config["environment"]["TR_SOURCE_BUNDLE_ROOT"] == "/opt/traderesearch/source-bundles"
        assert len(config["volumes"]) == 2
        assert all(item["read_only"] and not item["bind"]["create_host_path"] for item in config["volumes"])
        assert all(":?set " in item["source"] for item in config["volumes"])
    shell = ROOT / "deploy/docker/factortester-public/factortester-entrypoint.sh"
    assert 'export PYTHONPATH="${PYTHONPATH}:${TR_BUNDLE_PACKAGES_ROOT}"' in shell.read_text()
    subprocess.run(["bash", "-n", str(shell)], check=True)


def test_inventory_is_paginated_source_free_and_does_not_claim_migration():
    from sources.inventory import inventory_report
    report = inventory_report(ROOT / "sources", limit=2)
    following = inventory_report(ROOT / "sources", offset=2, limit=2)
    assert len(report["records"]) == 2
    assert report["member_ref_sha256"] == following["member_ref_sha256"]
    assert report["next_offset"] == 2
    assert report["data_migration_performed"] is False
    assert report["runtime_validated"] == 0
    assert report["needs_runtime_validation"] == 5


def test_external_root_is_explicit_and_client_code_is_not_activated(tmp_path):
    value = example()
    value.update(bundle_id="user-device", provisioner="user", execution_location="client", entrypoints=["not.installed.client"])
    write_manifest(tmp_path, value)
    import os
    completed = subprocess.run([sys.executable, "-S", "-c", "from sources.registry import installed_bundles,load_all_sources; assert installed_bundles()[0].provisioner=='user'; assert load_all_sources()==()"], cwd=ROOT, env={**os.environ,"TR_SOURCE_BUNDLE_ROOT":str(tmp_path)}, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr


def test_source_adapter_contract_import_has_no_platform_or_engine_dependencies():
    code = """
import sys
from traderesearch_data.nautilus import NautilusAdapterContract
from sources.LocalCNFutures.nautilus_adapter import CONTRACT_MIN1, CONTRACT_DAY1
assert isinstance(CONTRACT_MIN1, NautilusAdapterContract)
assert CONTRACT_DAY1.frequency == 'DAY1'
assert NautilusAdapterContract.__module__ == 'traderesearch_data.nautilus'
assert not any(name == 'tools' or name.startswith(('tools.', 'server.', 'nautilus_trader.')) for name in sys.modules)
"""
    subprocess.run([sys.executable, "-S", "-c", code], cwd=ROOT, check=True,
                   capture_output=True, text=True)


def test_lazy_bundle_paths_preserve_existing_artifact_resolution():
    import sources.LocalCNFutures as source
    from scripts.data_dir import DATA_DIR
    from tools.data.artifacts.storage import artifact_path, source_data_root

    assert source.SOURCE_DATA_DIR == str(source_data_root("LocalCNFutures", default=DATA_DIR))
    assert source.MINK_PRODUCT_DIR == source.SOURCE_DATA_DIR + "/data_mink_product"
    assert source.ROLLER_INFO_PATH == str(artifact_path("LocalCNFutures", "roller_info.parquet"))
    assert source.TERM_STRUCTURE_PATH == str(artifact_path("LocalCNFutures", "term_structure-listed_contracts.parquet"))
    with pytest.raises(AttributeError):
        getattr(source, "nonexistent_bundle_attribute")


def test_catalog_set_preserves_multiple_contracts_per_product(tmp_path):
    import pytest
    from traderesearch_data.nautilus import CatalogMemberRef, CatalogSet

    def ref(contract, bar_type):
        return CatalogMemberRef(
            authority="Local", bundle_id="Local", member_id="LocalCNFuturesContractMIN1",
            product_ref="T", source_product_ref="T.SHFE", contract_uid=contract,
            catalog_dir=tmp_path / contract, bar_type=bar_type,
        )

    first = ref("CFFEX|F|T|2403", "T2403.CFFEX-1-MINUTE-LAST-EXTERNAL")
    second = ref("CFFEX|F|T|2406", "T2406.CFFEX-1-MINUTE-LAST-EXTERNAL")
    catalog_set = CatalogSet((first, second))
    assert catalog_set.products() == ("T",)
    assert catalog_set.by_product("T") == (first, second)
    with pytest.raises(ValueError, match="duplicate catalog member reference"):
        CatalogSet((first, first))
    with pytest.raises(TypeError, match="must be a tuple"):
        CatalogSet([first])
    alternative = CatalogMemberRef(
        authority="Other", bundle_id="Local", member_id="LocalCNFuturesContractMIN1",
        product_ref="T", source_product_ref="T.SHFE", contract_uid="CFFEX|F|T|2403",
        catalog_dir=tmp_path / "other", bar_type="T2403.CFFEX-1-MINUTE-LAST-EXTERNAL",
    )
    assert CatalogSet((first, alternative)).by_product("T") == (first, alternative)
    with pytest.raises(ValueError, match="authority"):
        CatalogMemberRef(
            authority=None, bundle_id="Local", member_id="m", product_ref="T",
            source_product_ref="T.SHFE", contract_uid="CFFEX|F|T|2403",
            catalog_dir=tmp_path, bar_type="T2403.CFFEX-1-MINUTE-LAST-EXTERNAL",
        )
    with pytest.raises(TypeError, match="paths must be a tuple"):
        from traderesearch_data.nautilus import CatalogStagingRequest
        CatalogStagingRequest(["CFFEX|F|T|2403"])
    with pytest.raises(TypeError, match="catalog_dir"):
        CatalogMemberRef(
            authority="Local", bundle_id="Local", member_id="m", product_ref="T",
            source_product_ref="T.SHFE", contract_uid="CFFEX|F|T|2403",
            catalog_dir="not-a-path", bar_type="T2403.CFFEX-1-MINUTE-LAST-EXTERNAL",
        )


def test_public_rule_protocols_live_in_traderesearch_data():
    from traderesearch_data.rules import TradingFieldProvider, TradingFieldValue

    assert TradingFieldProvider.__module__ == "traderesearch_data.rules"
    assert TradingFieldValue.__module__ == "traderesearch_data.rules"


def test_installed_bundle_descriptors_are_metadata_only(monkeypatch):
    import pytest
    from server.services import product_catalog_projection as projection

    monkeypatch.setattr(
        projection, "load_all_sources",
        lambda: pytest.fail("metadata-only descriptor activated plugins"),
    )
    rows = projection.installed_bundle_descriptors()
    local = next(row for row in rows if row["bundle_id"] == "Local")
    assert local["availability"] == {"status": "unknown", "product_count": None}
    member = next(item for item in local["members"] if item["id"] == "LocalCNFuturesContractMIN1")
    assert "FieldHistory:market_rules:exchange" in member["related_members"]
    assert member["update_policy"]["mode"] == "mutable_history"
