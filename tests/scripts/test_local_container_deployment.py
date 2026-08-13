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
