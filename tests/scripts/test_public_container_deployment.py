from __future__ import annotations

import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
DEPLOYMENT = ROOT / "deploy" / "docker" / "factortester-public"


def _compose() -> dict:
    return yaml.safe_load((DEPLOYMENT / "compose.yaml").read_text(encoding="utf-8"))


def _published_container_ports(service: dict) -> set[int]:
    result: set[int] = set()
    for item in service.get("ports") or []:
        match = re.search(r":(\d+)(?:/(?:tcp|udp))?$", str(item))
        if match:
            result.add(int(match.group(1)))
    return result


def test_public_compose_has_exactly_two_business_containers() -> None:
    compose = _compose()

    assert set(compose["services"]) == {
        "factortester-public",
        "postgresql-control",
    }


def test_public_compose_never_publishes_internal_service_or_postgres() -> None:
    services = _compose()["services"]

    assert _published_container_ports(services["factortester-public"]) == {
        7998, 7997, 51820,
    }
    assert _published_container_ports(services["postgresql-control"]) == {51821}
    assert 8000 not in _published_container_ports(services["factortester-public"])
    assert 5432 not in _published_container_ports(services["postgresql-control"])


def test_public_compose_enforces_immutable_main_runtime() -> None:
    service = _compose()["services"]["factortester-public"]
    environment = service["environment"]

    assert environment["FACTORTESTER_HOT_RELOAD"] == "0"
    assert environment["FACTORTESTER_SERVICE_DEBUG"] == "0"
    assert environment["FACTORTESTER_ALLOW_PUBLIC_REGISTRATION"] == "0"
    assert environment["FACTORTESTER_REQUIRE_LOGIN_FOR_UI"] == "1"
    assert environment["FACTORTESTER_REQUIRE_DEVICE_AUTH"] == "1"
    assert service["restart"] == "unless-stopped"
    assert "depends_on" not in service


def test_public_image_excludes_development_only_dependencies() -> None:
    requirements = (
        ROOT / "deploy" / "requirements-public-linux.txt"
    ).read_text(encoding="utf-8")
    dockerfile = (DEPLOYMENT / "FactorTester.Dockerfile").read_text(
        encoding="utf-8",
    )

    assert "requirements-public-linux.txt" in dockerfile
    for package in ("pytest", "mypy", "watchdog"):
        assert not re.search(rf"(?m)^{package}(?:\[|[<=>])", requirements)


def test_public_image_includes_runtime_localizations_and_git() -> None:
    dockerfile = (DEPLOYMENT / "FactorTester.Dockerfile").read_text(
        encoding="utf-8",
    )

    assert "COPY apple/Resources apple/Resources" in dockerfile
    assert re.search(r"(?m)^\s+git \\?$", dockerfile)


def test_wireguard_identities_are_separate_and_db_has_no_swift_peer_source() -> None:
    services = _compose()["services"]
    app = services["factortester-public"]
    database = services["postgresql-control"]

    app_mounts = {str(item.get("target")) for item in app["volumes"] if isinstance(item, dict)}
    db_mounts = {str(item.get("target")) for item in database["volumes"] if isinstance(item, dict)}
    assert "/run/secrets/federation-wireguard" in app_mounts
    assert "/run/secrets/database-wireguard" not in app_mounts
    assert "/run/secrets/database-wireguard" in db_mounts
    assert "/run/secrets/federation-wireguard" not in db_mounts
    assert "FACTORTESTER_DB_ALLOWED_WIREGUARD_CIDRS" in database["environment"]
    assert "SWIFT" not in repr(database).upper()


def test_private_database_network_is_not_the_udp_transport_network() -> None:
    compose = _compose()
    networks = compose["networks"]
    services = compose["services"]

    assert networks["private"]["internal"] is True
    assert "internal" not in networks["transport"]
    assert services["factortester-public"]["networks"]["private"]["ipv4_address"] == "172.30.185.2"
    assert services["postgresql-control"]["networks"]["private"]["ipv4_address"] == "172.30.185.3"


def test_public_entrypoint_uses_184_peer_contract_without_public_mapping() -> None:
    entrypoint = (DEPLOYMENT / "factortester-entrypoint.sh").read_text(encoding="utf-8")

    assert "--peer-host" in entrypoint
    assert "--peer-port 17998" in entrypoint
    assert "--peer-data-port 17997" in entrypoint
    assert "17998:" not in (DEPLOYMENT / "compose.yaml").read_text(encoding="utf-8")
    assert "17997:" not in (DEPLOYMENT / "compose.yaml").read_text(encoding="utf-8")
