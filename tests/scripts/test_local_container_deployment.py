"""Reproducible contract for the local Docker Manager deployment."""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
DEPLOYMENT = ROOT / "deploy" / "docker" / "factortester-server"


def _compose() -> dict:
    return yaml.safe_load((DEPLOYMENT / "compose.yaml").read_text(encoding="utf-8"))


def test_local_compose_defaults_to_canonical_client_ports() -> None:
    ports = _compose()["services"]["wireguard"]["ports"]

    assert any(":-7998}:7998" in item for item in ports)
    assert any(":-7997}:7997" in item for item in ports)
    assert all("27998" not in item and "27997" not in item for item in ports)


def test_local_manager_enables_wireguard_only_peer_surfaces() -> None:
    compose = _compose()
    manager = compose["services"]["manager"]
    command = manager["command"]
    published = " ".join(compose["services"]["wireguard"]["ports"])

    assert "--overlay-bind-address" in command
    assert "${FACTORTESTER_FEDERATION_LOCAL_ADDRESS:?set FACTORTESTER_FEDERATION_LOCAL_ADDRESS}" in command
    assert "FACTORTESTER_PEER_ADDRESS" not in repr(compose)
    assert "--peer-port" in command
    assert "17998" in command
    assert "--peer-data-port" in command
    assert "17997" in command
    assert "17998" not in published
    assert "17997" not in published
    assert "${FACTORTESTER_SERVER_ID:?set FACTORTESTER_SERVER_ID}" in command


def test_local_manager_defaults_to_fixed_feat_service_7999() -> None:
    compose = _compose()
    manager = compose["services"]["manager"]
    command = manager["command"]

    assert "--fixed-port" in command
    assert "${FACTORTESTER_FIXED_PORT:-7999}" in command
    assert "--fixed-branch" in command
    assert "${FACTORTESTER_FIXED_BRANCH:-feat}" in command
    assert manager["environment"]["FACTORTESTER_START_FIXED_SERVICE"] == (
        "${FACTORTESTER_START_FIXED_SERVICE:-1}"
    )

    published = " ".join(compose["services"]["wireguard"]["ports"])
    assert ":7999" not in published


def test_local_manager_mounts_existing_runtime_data_root() -> None:
    manager = _compose()["services"]["manager"]
    mounts = {
        (item.get("source"), item.get("target"))
        for item in manager["volumes"]
        if isinstance(item, dict)
    }

    expected = (
        "${FACTORTESTER_RUNTIME_DATA_ROOT:?set "
        "FACTORTESTER_RUNTIME_DATA_ROOT}",
    )
    assert (expected[0], expected[0]) in mounts
    assert "FACTORTESTER_RUNTIME_DATA_ROOT=" in (
        DEPLOYMENT / "server.env.example"
    ).read_text(encoding="utf-8")


def test_local_manager_can_import_vendored_research_contracts() -> None:
    python_path = _compose()["services"]["manager"]["environment"]["PYTHONPATH"]

    assert python_path == "${FACTORTESTER_REPO_ROOT:?set FACTORTESTER_REPO_ROOT}"
