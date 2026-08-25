"""Visitor catalog and server-address projections."""

from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

import pytest

from server.manager import runtime as manager
from server.manager.domain.federation import ServiceRoute
from server.manager.services.network_info import server_network_info
from server.manager.services.public_catalog import public_factor_library
from server.manager.state.routing import RoutingStateMixin


@contextmanager
def running_manager(state):
    manager.Handler.state = state
    server = manager.ThreadingHTTPServer(("127.0.0.1", 0), manager.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


class Registry:
    def __init__(self, servers):
        self._servers = servers

    def servers(self, *, include_offline=False):
        return [item for item in self._servers if include_offline or item["online"]]


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def _server(server_id, endpoint, *, public=True, internal=None):
    return {
        "server_id": server_id,
        "role": "main" if public else "feat",
        "public_server": public,
        "internal_addresses": list(internal or []),
        "endpoint": endpoint,
        "online": True,
        "latency_ms": 5,
        "load": {"load": 1, "active_jobs": 0, "queue_depth": 0},
        "revision": "r1",
    }


def test_network_info_lists_current_and_at_most_three_public_ip_hosts():
    registry = Registry([
        _server("public-1", "https://198.51.100.1:7998"),
        _server("public-2", "https://198.51.100.2:7998"),
        _server("public-3", "https://198.51.100.3:7998"),
        _server("public-4", "https://198.51.100.4:7998"),
        _server("internal-1", "https://192.168.10.8:7998", public=False,
                internal=["192.168.10.8"]),
    ])
    value = server_network_info(
        registry=registry,
        federation_config={},
        source_server_id="public-0",
        server_role="main",
        public_server=True,
        manager_public_endpoint="https://198.51.100.0:7998",
    )

    assert value["public_server_addresses"] == [
        "198.51.100.0", "198.51.100.1", "198.51.100.2",
    ]
    assert value["internal_server_addresses"] == ["192.168.10.8"]


def test_public_factor_library_contains_public_metadata_only(monkeypatch):
    from server.modules.custom_factors import catalog

    monkeypatch.setattr(catalog, "list_public_factors", lambda: [{
        "id": "momentum",
        "name": "Momentum",
        "factor_family": "MomentumFamily",
        "description": "public description",
        "family_formula_fingerprint": "a" * 64,
        "source_code": "SECRET SOURCE",
        "params": [{"alias": "window", "value": "20"}],
        "is_public": True,
    }, {
        "id": "volatility",
        "name": "Volatility",
        "factor_family": "FactorFamily",
        "description": "public volatility",
        "family_formula_fingerprint": "b" * 64,
        "params": [],
        "is_public": True,
    }])

    value = public_factor_library()

    assert value["principal"] == "__public_jobs__"
    assert value["factors"] == []
    assert [item["factor_family_alias"] for item in value["families"]] == [
        "momentum", "volatility",
    ]
    assert value["families"][0]["factor_count"] == 0
    assert value["families"][0]["params"] == [
        {"alias": "window", "value": "20", "redacted": False},
    ]
    assert "source_code" not in value["families"][0]


def test_source_provider_extracts_endpoint_host():
    route = ServiceRoute(
        server_id="public-1",
        role="main",
        branch="main",
        revision="r1",
        port=7998,
        endpoint="https://198.51.100.1:7998",
        public_server=True,
    )

    value = RoutingStateMixin._source_provider(route)

    assert value["server_host"] == "198.51.100.1"
    assert value["public_server"] is True


def test_compliance_page_uses_public_allowlist_visitor_enrollment():
    from server.manager.http.pages import compliance_page

    body = compliance_page("/jobs").decode("utf-8")

    assert "当前浏览器来源没有已登记的设备密钥" in body
    assert "白名单用户请点击访客模式" in body
    assert "内网设置页" not in body
    assert "deviceAuthTarget" not in body
    assert "device-auth-target" not in body


def test_removed_internal_device_registration_routes_are_not_present(tmp_path):
    state = manager.ManagerState(tmp_path, "python")

    with running_manager(state) as base_url:
        for path in (
            "/device-authorize",
            "/api/device/public-targets",
        ):
            with pytest.raises(HTTPError) as failed:
                urlopen(f"{base_url}{path}")
            assert failed.value.code == 404

        for path in (
            "/api/device/authorization",
            "/api/device/authorization/redeem",
        ):
            request = Request(
                f"{base_url}{path}",
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with pytest.raises(HTTPError) as failed:
                urlopen(request)
            assert failed.value.code == 404


def test_visitor_entry_is_marked_for_testing_only():
    from server.manager.http.pages import compliance_page

    body = compliance_page(
        "/jobs",
        visitor_entry_href="/visitor?next=/jobs",
    ).decode("utf-8")

    assert 'class="visitor-entry"' in body
    assert 'class="visitor-test-note"' in body
    assert "（仅供测试使用）" in body


def test_compliance_request_from_configured_alias_points_to_public_ip(
    tmp_path, monkeypatch,
):
    monkeypatch.setenv("FACTORTESTER_REQUIRE_LOGIN_FOR_UI", "1")
    monkeypatch.setenv("FACTORTESTER_REQUIRE_DEVICE_AUTH", "1")
    monkeypatch.setenv("FACTORTESTER_PUBLIC_SERVER", "1")
    monkeypatch.setenv(
        "FACTORTESTER_MANAGER_PUBLIC_ENDPOINT",
        "https://198.51.100.10:7998",
    )
    monkeypatch.setenv(
        "FACTORTESTER_PUBLIC_VISITOR_ORIGINS",
        "https://eloquence-drizzly-fencing.ngrok-free.dev",
    )
    state = manager.ManagerState(tmp_path, "python", server_id="public-0")
    headers = {
        "Host": "eloquence-drizzly-fencing.ngrok-free.dev",
        "X-Forwarded-Proto": "https",
        "X-Forwarded-For": "8.8.8.8",
    }

    opener = build_opener(_NoRedirect())
    with running_manager(state) as base_url:
        with pytest.raises(HTTPError) as redirected:
            opener.open(Request(
                f"{base_url}/compliance?next=/jobs",
                headers=headers,
            ))
        assert redirected.value.code == 303
        location = redirected.value.headers["Location"]
        assert location.startswith(
            "https://198.51.100.10:7998/compliance?"
        )
        grant = parse_qs(urlparse(location).query)["grant"][0]
        target = Request(
            f"{base_url}/compliance?grant={grant}&next=%2Fjobs",
            headers={
                "Host": "198.51.100.10:7998",
                "X-Forwarded-Proto": "https",
                "X-Forwarded-For": "8.8.8.8",
            },
        )
        with urlopen(target) as response:
            body = response.read().decode("utf-8")

    assert 'class="visitor-entry"' in body
    assert f"grant={grant}" in body
    assert 'id="device-auth-status"' in body


def test_visitor_catalog_shows_internal_sources_but_rejects_their_data(
    tmp_path, monkeypatch,
):
    monkeypatch.setenv("FACTORTESTER_REQUIRE_LOGIN_FOR_UI", "1")
    monkeypatch.setenv("FACTORTESTER_REQUIRE_DEVICE_AUTH", "1")
    monkeypatch.setenv("FACTORTESTER_PUBLIC_SERVER", "1")
    monkeypatch.setenv(
        "FACTORTESTER_MANAGER_PUBLIC_ENDPOINT",
        "https://198.51.100.10:7998",
    )
    state = manager.ManagerState(tmp_path, "python", server_id="public-0")
    descriptors = [
        {
            "id": "PublicSource",
            "source_name": "公网数据源",
            "server_providers": [{
                "server_id": "public-0", "online": True,
                "public_server": True,
            }],
        },
        {
            "id": "InternalSource",
            "source_name": "内网数据源",
            "server_providers": [{
                "server_id": "internal-1", "online": True,
                "public_server": False,
            }],
        },
    ]
    monkeypatch.setattr(
        state, "federated_source_descriptors", lambda **_: descriptors,
    )
    monkeypatch.setattr(
        state.client_state, "product_names", lambda *_: [
            {"name": "public-product", "source_ids": ["PublicSource"]},
            {"name": "internal-product", "source_ids": ["InternalSource"]},
        ],
    )
    grant = state.visitor_access.issue_grant(
        "https://198.51.100.10:7998",
    )
    visitor_token = state.visitor_access.redeem_grant(
        grant, target_origin="https://198.51.100.10:7998",
    )
    headers = {
        "Host": "198.51.100.10:7998",
        "X-Forwarded-Proto": "https",
        "X-Forwarded-For": "8.8.8.8",
        "Cookie": f"ft-manager-visitor={visitor_token}",
    }

    with running_manager(state) as base_url:
        with urlopen(Request(
            f"{base_url}/api/catalog/sources", headers=headers,
        )) as response:
            sources = json.loads(response.read())["sources"]
        with urlopen(Request(
            f"{base_url}/api/catalog/products?data_source=PublicSource",
            headers=headers,
        )) as response:
            products = json.loads(response.read())["products"]
        with pytest.raises(HTTPError) as denied:
            urlopen(Request(
                f"{base_url}/api/catalog/products?data_source=InternalSource",
                headers=headers,
            ))

    by_id = {item["id"]: item for item in sources}
    assert by_id["PublicSource"]["visitor_data_accessible"] is True
    assert by_id["InternalSource"]["visitor_data_accessible"] is False
    assert [item["name"] for item in products] == ["public-product"]
    assert denied.value.code == 403


def test_visitor_can_read_public_price_series_but_not_internal_product_prices(
    tmp_path, monkeypatch,
):
    monkeypatch.setenv("FACTORTESTER_REQUIRE_LOGIN_FOR_UI", "1")
    monkeypatch.setenv("FACTORTESTER_REQUIRE_DEVICE_AUTH", "1")
    monkeypatch.setenv("FACTORTESTER_PUBLIC_SERVER", "1")
    state = manager.ManagerState(tmp_path, "python", server_id="public-0")
    descriptors = [{
        "id": "PublicSource",
        "server_providers": [{
            "server_id": "public-0", "online": True,
            "public_server": True,
        }],
    }, {
        "id": "InternalSource",
        "server_providers": [{
            "server_id": "internal-1", "online": True,
            "public_server": False,
        }],
    }]
    monkeypatch.setattr(
        state, "federated_source_descriptors", lambda **_: descriptors,
    )

    def product_fields(name):
        source_id = "PublicSource" if name == "public-product" else "InternalSource"
        return {"name": name, "source_ids": [source_id]}

    monkeypatch.setattr(state.client_state, "product_fields", product_fields)
    calls = []

    def price_series(payload):
        calls.append(payload)
        return {
            "success": True,
            "product": payload["product_name"],
            "adjusted": False,
            "data": [{"timestamp": "2026-01-02", "close": 1}],
        }

    monkeypatch.setattr(
        state.client_state, "product_price_series", price_series,
    )
    grant = state.visitor_access.issue_grant(
        "https://198.51.100.10:7998",
    )
    visitor_token = state.visitor_access.redeem_grant(
        grant, target_origin="https://198.51.100.10:7998",
    )
    headers = {
        "Host": "198.51.100.10:7998",
        "X-Forwarded-Proto": "https",
        "Cookie": f"ft-manager-visitor={visitor_token}",
        "Content-Type": "application/json",
    }

    def post(base_url, product_name):
        body = json.dumps({"product_name": product_name}).encode()
        request_headers = {**headers, "Content-Length": str(len(body))}
        return urlopen(Request(
            f"{base_url}/api/catalog/prices",
            data=body, headers=request_headers, method="POST",
        ))

    with running_manager(state) as base_url:
        with post(base_url, "public-product") as response:
            value = json.loads(response.read())
        with pytest.raises(HTTPError) as denied:
            post(base_url, "internal-product")

    assert value["success"] is True
    assert calls == [{"product_name": "public-product"}]
    assert denied.value.code == 403


def test_visitor_can_load_test_workbench_without_account_session(
    tmp_path, monkeypatch,
):
    """Anonymous visitor capability is sufficient for the test editor shell."""
    monkeypatch.setenv("FACTORTESTER_REQUIRE_LOGIN_FOR_UI", "1")
    monkeypatch.setenv("FACTORTESTER_REQUIRE_DEVICE_AUTH", "1")
    monkeypatch.setenv("FACTORTESTER_PUBLIC_SERVER", "1")
    state = manager.ManagerState(tmp_path, "python", server_id="public-0")
    grant = state.visitor_access.issue_grant(
        "https://198.51.100.10:7998",
    )
    visitor_token = state.visitor_access.redeem_grant(
        grant, target_origin="https://198.51.100.10:7998",
    )
    headers = {
        "Host": "198.51.100.10:7998",
        "X-Forwarded-Proto": "https",
        "Cookie": f"ft-manager-visitor={visitor_token}",
    }

    with running_manager(state) as base_url:
        with urlopen(Request(
            f"{base_url}/api/backtest/settings/group_test/summary",
            headers=headers,
        )) as response:
            settings = json.loads(response.read())
        with urlopen(Request(
            f"{base_url}/api/workspace-summaries",
            headers=headers,
        )) as response:
            workspaces = json.loads(response.read())

    assert settings["success"] is True
    assert settings["application"] == "group_test"
    assert any(settings["tab_lists"].values())
    assert workspaces == {"success": True, "workspaces": []}
