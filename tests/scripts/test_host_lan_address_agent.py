from __future__ import annotations

import json
from pathlib import Path

from scripts.server import host_lan_address_agent


class FakeRunner:
    def __init__(self, responses: dict[tuple[str, ...], str]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, command: tuple[str, ...]) -> str:
        self.calls.append(command)
        return self.responses.get(command, "")


def test_macos_discovers_active_hardware_interface_without_fixed_device() -> None:
    runner = FakeRunner({
        ("networksetup", "-listallhardwareports"): """
Hardware Port: Wi-Fi
Device: en7
Ethernet Address: 00:11:22:33:44:55
""",
        ("route", "-n", "get", "default"): "interface: en7\n",
        ("ipconfig", "getifaddr", "en7"): "10.98.186.177\n",
    })

    assert host_lan_address_agent.discover_lan_addresses(
        system="Darwin",
        run=runner,
    ) == ["10.98.186.177"]
    assert ("ipconfig", "getifaddr", "en0") not in runner.calls


def test_linux_prefers_physical_default_route_over_virtual_route() -> None:
    routes = [
        {"dst": "default", "dev": "wg0", "metric": 10},
        {"dst": "default", "dev": "wlp4s0", "metric": 600},
    ]
    runner = FakeRunner({
        ("ip", "-json", "route", "show", "default"): json.dumps(routes),
        ("ip", "-json", "link", "show", "dev", "wg0"): json.dumps([{
            "ifname": "wg0",
            "linkinfo": {"info_kind": "wireguard"},
        }]),
        ("ip", "-json", "link", "show", "dev", "wlp4s0"): json.dumps([{
            "ifname": "wlp4s0",
            "link_type": "ether",
        }]),
        ("ip", "-json", "addr", "show", "dev", "wlp4s0"): json.dumps([{
            "addr_info": [{
                "family": "inet",
                "local": "192.168.50.12",
                "scope": "global",
            }],
        }]),
    })

    assert host_lan_address_agent.discover_lan_addresses(
        system="Linux",
        run=runner,
    ) == ["192.168.50.12"]


def test_windows_uses_hardware_adapter_selected_by_default_route() -> None:
    runner = FakeRunner({
        ("powershell", "-NoProfile", "-NonInteractive", "-Command",
         host_lan_address_agent.WINDOWS_DISCOVERY_SCRIPT): json.dumps({
            "IPAddress": "172.16.4.8",
        }),
    })

    assert host_lan_address_agent.discover_lan_addresses(
        system="Windows",
        run=runner,
    ) == ["172.16.4.8"]


def test_unknown_platform_does_not_guess_an_address() -> None:
    assert host_lan_address_agent.discover_lan_addresses(
        system="Plan9",
        run=FakeRunner({}),
    ) == []


def test_snapshot_write_is_versioned_and_timestamped(tmp_path: Path) -> None:
    output = tmp_path / "host-lan-addresses.json"

    host_lan_address_agent.write_snapshot(
        output,
        ["10.0.0.8"],
        observed_at=123.5,
    )

    assert json.loads(output.read_text(encoding="utf-8")) == {
        "schema_version": 1,
        "observed_at": 123.5,
        "addresses": ["10.0.0.8"],
    }

