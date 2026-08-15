from __future__ import annotations

import hashlib
import json
from pathlib import Path

from server.manager.web import assets as research_static


ROOT = Path(__file__).resolve().parents[2]
WEB_ROOT = ROOT / "server" / "manager" / "web"
CYTOSCAPE = ROOT / "static" / "vendor" / "cytoscape"


def test_research_graph_renderer_is_bundled_and_declared() -> None:
    manifest = json.loads((WEB_ROOT / "module-manifest.json").read_text())
    asset = "vendor/cytoscape/cytoscape.min.js"

    assert asset in manifest["external_scripts"]
    assert manifest["group_external_scripts"]["research"] == [asset]
    body, content_type = research_static.static_file(asset)
    assert body == (CYTOSCAPE / "cytoscape.min.js").read_bytes()
    assert content_type == "text/javascript"

    checksum = json.loads((CYTOSCAPE / "checksums.json").read_text())
    actual = CYTOSCAPE / "cytoscape.min.js"
    assert hashlib.sha256(actual.read_bytes()).hexdigest() == checksum["files"]["cytoscape.min.js"]["sha256"]
    assert actual.stat().st_size == checksum["files"]["cytoscape.min.js"]["bytes"]
    assert (CYTOSCAPE / "LICENSE").is_file()


def test_graph_page_uses_network_canvas_and_yaml_download() -> None:
    source = (WEB_ROOT / "research" / "graph.js").read_text()

    assert "window.cytoscape" in source
    assert "research-graph-canvas" in source
    assert "/yaml" in source
    assert "download" in source
    assert "viewUserGraph" in source
    assert "research-graph-user-preview" in source
    assert "nodeList" not in source
    assert "edgeList" not in source
