from __future__ import annotations

import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

import pytest
import yaml

import settings as Settings
from server.manager import runtime as manager
from server.manager.http.research_graph_catalog_routes import (
    is_public_research_graph_catalog_read,
)
from server.services.research_graph.protocol import graph_content_hash


def _graph() -> dict[str, object]:
    graph: dict[str, object] = {
        "schema_version": 1,
        "graph_id": "manager-catalog-test",
        "version": 1,
        "lifecycle": "observed",
        "parent_version": 0,
        "research_semantics": "product_neutral",
        "nodes": [{
            "node_id": "hypothesis",
            "kind": "research",
            "purpose": "freeze hypothesis",
            "enforcement": "audited",
            "required_capabilities": [],
            "entry_evidence": [],
            "exit_evidence": [],
        }],
        "edges": [],
        "provenance": {"source": "manager-test"},
    }
    graph["content_hash"] = graph_content_hash(graph)
    return graph


@pytest.fixture()
def manager_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "manager.sqlite")
    state = manager.ManagerState(
        tmp_path,
        "python",
        server_id="manager-test",
        state_root=tmp_path / "state",
        session_db_path=Settings.CACHE_DB_PATH,
    )
    token, _, _ = state._issue_session(
        "GTHT@Admin@1",
        "super_admin",
        alias="Admin",
    )
    manager.Handler.state = state
    server = ThreadingHTTPServer(("127.0.0.1", 0), manager.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, token, state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _request(server, token: str, path: str, *, method: str = "GET", payload=None):
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Authorization": f"Bearer {token}"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = Request(
        f"http://127.0.0.1:{server.server_port}{path}",
        headers=headers,
        data=body,
        method=method,
    )
    with urlopen(request) as response:
        return response.status, response.headers, response.read()


def test_manager_owns_graph_catalog_without_a_service_port(manager_server) -> None:
    server, token, _state = manager_server
    graph = _graph()
    status, _, _ = _request(
        server,
        token,
        "/api/catalog/research-graphs/versions",
        method="POST",
        payload={"graph": graph},
    )
    assert status == 201

    status, _, _ = _request(
        server,
        token,
        "/api/catalog/research-graphs/manager-catalog-test/versions/1/presentations",
        method="POST",
        payload={"presentation": {
            "schema_version": 1,
            "graph_id": "manager-catalog-test",
            "version": 1,
            "locale": "en",
            "title": "Manager catalog test",
            "nodes": {"hypothesis": {"label": "Hypothesis"}},
        }},
    )
    assert status == 201

    status, _, body = _request(
        server,
        token,
        "/api/catalog/research-graphs/manager-catalog-test/versions",
    )
    assert status == 200
    assert json.loads(body)["versions"][0]["version"] == 1

    with urlopen(
        f"http://127.0.0.1:{server.server_port}"
        "/api/catalog/research-graphs/manager-catalog-test/versions"
    ) as response:
        assert response.status == 200
        assert json.loads(response.read())["versions"][0]["version"] == 1

    status, _, _ = _request(
        server,
        token,
        "/api/catalog/research-graphs/manager-catalog-test/versions/1/activate",
        method="POST",
        payload={},
    )
    assert status == 201

    status, headers, body = _request(
        server,
        token,
        "/api/catalog/research-graphs/manager-catalog-test/versions/1/yaml",
    )
    assert status == 200
    assert headers["X-FactorTester-Graph-Version"] == "1"
    assert yaml.safe_load(body.decode("utf-8"))["graph_id"] == (
        "manager-catalog-test"
    )

    status, headers, _ = _request(
        server,
        token,
        "/api/catalog/research-graphs/manager-catalog-test/versions/1/yaml?locale=en",
    )
    assert status == 200
    assert headers["Content-Language"] == "en"


def test_manager_graph_user_library_is_owner_scoped(manager_server) -> None:
    server, token, _state = manager_server
    raw_yaml = yaml.safe_dump(_graph(), allow_unicode=True)
    status, _, body = _request(
        server,
        token,
        "/api/catalog/research-graphs/user-library",
        method="POST",
        payload={"filename": "personal.yaml", "yaml": raw_yaml},
    )
    assert status == 201
    file_id = json.loads(body)["file"]["graph_file_id"]

    status, _, body = _request(
        server,
        token,
        "/api/catalog/research-graphs/user-library",
    )
    assert status == 200
    assert json.loads(body)["files"][0]["graph_file_id"] == file_id

    status, _, body = _request(
        server,
        token,
        f"/api/catalog/research-graphs/user-library/{file_id}?view=1",
    )
    assert status == 200
    assert json.loads(body)["file"]["graph"]["graph_id"] == (
        "manager-catalog-test"
    )

    status, _, _ = _request(
        server,
        token,
        f"/api/catalog/research-graphs/user-library/{file_id}",
        method="DELETE",
    )
    assert status == 200


def test_only_immutable_server_graph_catalog_paths_are_public() -> None:
    prefix = "/api/catalog/research-graphs/factor-research"
    assert is_public_research_graph_catalog_read(f"{prefix}/versions")
    assert is_public_research_graph_catalog_read(f"{prefix}/active")
    assert is_public_research_graph_catalog_read(
        f"{prefix}/versions/1/presentations"
    )
    assert is_public_research_graph_catalog_read(
        f"{prefix}/versions/1/yaml"
    )
    assert not is_public_research_graph_catalog_read(
        "/api/catalog/research-graphs/versions"
    )
    assert not is_public_research_graph_catalog_read(
        "/api/catalog/research-graphs/user-library"
    )
    assert not is_public_research_graph_catalog_read(
        f"{prefix}/versions/1/activate"
    )
