from pathlib import Path

import yaml


def test_data_only_compose_has_no_manager_or_execution_worker() -> None:
    root = Path(__file__).resolve().parents[2]
    compose = yaml.safe_load((root / "deploy/docker/data-node/compose.yaml").read_text())
    assert set(compose["services"]) == {"data-io"}
    service = compose["services"]["data-io"]
    assert service["command"] == ["python", "-m", "server.data_io.service"]
    assert service["environment"]["TR_DATA_CACHE_AUTHORITY"] == "${TR_DATA_NODE_ID:?set stable data-node cache authority}"
    assert service["environment"]["TR_DATA_IO_ALLOWED_ROOTS"] == "/data"
    assert not any("secret" in str(volume).lower() for volume in service["volumes"])
    assert service["mem_limit"] == "${TR_DATA_IO_MEMORY:-1g}"
