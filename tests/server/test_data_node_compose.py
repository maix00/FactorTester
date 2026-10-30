from pathlib import Path

import yaml


def test_data_only_compose_has_no_manager_or_execution_worker() -> None:
    root = Path(__file__).resolve().parents[2]
    compose = yaml.safe_load((root / "deploy/docker/data-node/compose.yaml").read_text())
    assert set(compose["services"]) == {"data-io"}
    service = compose["services"]["data-io"]
    assert service["entrypoint"] == []
    assert service["command"] == ["python", "-m", "server.data_io.service"]
    assert service["environment"]["TR_DATA_CACHE_AUTHORITY"] == "${TR_DATA_NODE_ID:?set stable data-node cache authority}"
    assert service["environment"]["TR_DATA_IO_ALLOWED_ROOTS"] == "/data"
    assert not any("secret" in str(volume).lower() for volume in service["volumes"])
    assert service["mem_limit"] == "${TR_DATA_IO_MEMORY:-1g}"


def test_execution_consumers_mount_node_local_settings() -> None:
    root = Path(__file__).resolve().parents[2]
    compose = yaml.safe_load((root / "deploy/docker/execution-node/compose.yaml").read_text())
    expected = "${TR_NODE_RUNTIME_SETTINGS:?set node-local runtime settings file}:/opt/factortester/.settings:ro"
    for name in ("worker", "market"):
        assert expected in compose["services"][name]["volumes"]
    assert expected not in compose["services"]["data-io"]["volumes"]
