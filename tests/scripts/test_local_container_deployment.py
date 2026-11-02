"""Reproducible contract for the local Docker Manager deployment."""

import json
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


def test_local_agent_has_shared_pinned_tools_after_existing_python_layer() -> None:
    dockerfile = (DEPLOYMENT / "FactorTester.Dockerfile").read_text()
    public = (ROOT / "deploy/docker/factortester-public/FactorTester.Dockerfile").read_text()
    installer = (DEPLOYMENT / "install-agent-tools.sh").read_text()
    assert " AS manager-base" in dockerfile
    assert dockerfile.index("pip install --no-cache-dir -r /tmp/requirements-linux.txt") < dockerfile.index("FROM manager-runtime AS traderesearch-local-manager")
    assert "bubblewrap=0.12.0-1~deb13u1" in dockerfile
    assert "chmod 0755 /usr/bin/bwrap" in dockerfile
    assert "COPY deploy/docker/factortester-server/install-agent-tools.sh" in dockerfile
    assert "COPY deploy/docker/factortester-server/install-agent-tools.sh" in public
    assert "Codex platform package integrity check failed" in installer
    assert "cc_switch_sha256=" in installer
    assert "COPY --from=traderesearch-local-cli-builder /runtime /usr/local/lib/traderesearch-cli" in dockerfile
    assert "/usr/local/bin/traderesearch" in dockerfile
    assert dockerfile.rstrip().endswith("USER factortester")


def test_local_agent_uses_restricted_namespaces_and_keeps_network_sidecar_separate() -> None:
    services = _compose()["services"]
    manager, wireguard = services["manager"], services["wireguard"]
    assert manager["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in manager["security_opt"]
    assert any("agent-seccomp.json" in item for item in manager["security_opt"])
    assert all("unconfined" not in item for item in manager["security_opt"])
    assert wireguard["cap_add"] == ["NET_ADMIN"]
    profile = json.loads((DEPLOYMENT / "agent-seccomp.json").read_text())
    assert profile["defaultAction"] == "SCMP_ACT_ERRNO"
    unshare, clone, mounts = profile["syscalls"][-3:]
    assert unshare["names"] == ["unshare"] and clone["names"] == ["clone"]
    allowed_namespaces = 0x10000000 | 0x00020000 | 0x04000000 | 0x08000000 | 0x20000000 | 0x02000000
    assert unshare["args"][0]["value"] == (2**64 - 1) ^ allowed_namespaces
    assert clone["args"][0]["value"] == (2**64 - 1) ^ (allowed_namespaces | 255)
    assert mounts["names"] == ["mount", "umount2", "pivot_root"]
    assert not any("ptrace" in item["names"] for item in profile["syscalls"][-3:])


def test_local_base_reuse_always_refreshes_pinned_alpha_before_cli_and_agent() -> None:
    dockerfile = (DEPLOYMENT / "FactorTester.Dockerfile").read_text()
    base, runtime = dockerfile.split("FROM manager-base AS manager-runtime", 1)
    assert "COPY --from=alpha-builder" not in base
    alpha_install, consumers = runtime.split("# The CLI is", 1)
    assert "COPY --from=alpha-builder /wheels /tmp/alpha-wheels" in alpha_install
    assert "--no-deps --force-reinstall /tmp/alpha-wheels/*.whl" in alpha_install
    assert "FROM manager-runtime AS traderesearch-local-cli-builder" in consumers
    assert "FROM manager-runtime AS traderesearch-local-manager" in consumers


def test_local_build_context_excludes_nested_native_and_python_outputs() -> None:
    patterns = (DEPLOYMENT / "FactorTester.Dockerfile.dockerignore").read_text().splitlines()
    include = patterns.index("!vendor/py-alpha-lib/**")
    for pattern in ("**/target", "**/__pycache__", "**/*.so", "**/*.dylib"):
        assert patterns.index(pattern) > include
    assert "!deploy/docker/factortester-server/install-agent-tools.sh" in patterns
