from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from sources.Tiger.connector import TigerConnector, TigerConnectorConfig
from sources.Tiger.products import get_all_jp_futures


def test_tiger_probe_separates_realtime_entitlement_from_verified_latency(
    tmp_path,
):
    props = tmp_path / "paper.properties"
    props.write_text("private_key=must-not-leave-connector\n", encoding="utf-8")
    bridge = tmp_path / "fake_tiger_bridge.py"
    bridge.write_text(
        """
import json
import sys

request = json.load(sys.stdin)
assert request == {
    "operation": "availability",
    "products": [
        {"name": "JNI.OSE", "identifier": "JNImain"},
        {"name": "JMI.OSE", "identifier": "JMImain"},
    ],
    "expanded": False,
}
print(json.dumps({
    "status": "ok",
    "received_at_ms": 1784322010000,
    "permissions": [{"name": "OSEFuturesQuoteLv2", "expire_at": 1786860568000}],
    "quotes": [
        {"identifier": "JNImain", "latest_time": 1784322001028},
        {"identifier": "JMImain", "latest_time": 1784322001029},
    ],
}))
""",
        encoding="utf-8",
    )
    connector = TigerConnector(TigerConnectorConfig(
        python_path=sys.executable,
        props_path=str(props),
        bridge_path=str(bridge),
        timeout_seconds=5,
    ))

    entries = connector.inspect(
        get_all_jp_futures()[:2],
        probe=True,
        expanded=False,
    )

    assert [entry["status"] for entry in entries] == ["available", "available"]
    assert all(entry["mode"] == "live_stream" for entry in entries)
    assert all(entry["entitled_realtime"] is True for entry in entries)
    assert all(entry["latency_class"] == "unverified" for entry in entries)
    assert entries[0]["observed_age_ms"] == 8972
    assert "must-not-leave-connector" not in json.dumps(entries)


def test_tiger_static_availability_never_spawns_or_claims_live_data(tmp_path):
    connector = TigerConnector(TigerConnectorConfig(
        python_path=str(tmp_path / "missing-python"),
        props_path=str(tmp_path / "missing.properties"),
        bridge_path=str(tmp_path / "missing-bridge.py"),
        timeout_seconds=1,
    ))

    entries = connector.inspect(
        get_all_jp_futures(),
        probe=False,
        expanded=False,
    )

    assert len(entries) == 5
    assert all(entry["status"] == "unavailable" for entry in entries)
    assert all(entry["connection"] == "not_probed" for entry in entries)
    assert all(entry["entitled_realtime"] is None for entry in entries)
    assert all(entry["latency_class"] == "unverified" for entry in entries)


def test_tiger_bridge_rejects_non_readonly_operation_without_loading_sdk():
    bridge = (
        Path(__file__).parents[2]
        / "sources"
        / "Tiger"
        / "bridge.py"
    )

    completed = subprocess.run(
        [sys.executable, str(bridge)],
        input=json.dumps({"operation": "place_order"}),
        text=True,
        capture_output=True,
        check=False,
        timeout=5,
    )

    assert completed.returncode == 0
    assert json.loads(completed.stdout) == {
        "status": "error",
        "error_code": "operation_not_allowed",
    }
