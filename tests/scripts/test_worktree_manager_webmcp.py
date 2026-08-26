"""Contracts for the browser-owned FactorTester WebMCP surface."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WEB_ROOT = ROOT / "server" / "manager" / "web"


def test_webmcp_module_is_loaded_before_the_coordinator() -> None:
    manifest = json.loads((WEB_ROOT / "module-manifest.json").read_text())
    app = manifest["groups"]["app"]

    assert "app/webmcp.js" in app
    assert app.index("app/webmcp.js") < app.index("app/coordinator.js")


def test_webmcp_browser_contract() -> None:
    fixture = ROOT / "tests" / "scripts" / "fixtures" / "webmcp.js"
    result = subprocess.run(
        ["node", str(fixture)], cwd=ROOT, capture_output=True, text=True, check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_webmcp_capability_catalog_covers_public_cli_root_commands() -> None:
    source = (WEB_ROOT / "app" / "webmcp.js").read_text()
    for command in (
        "configure", "client", "login", "logout", "doctor", "factor-plan",
        "list", "protocol", "describe", "edit", "strategy-intent", "strategy",
        "margin-budget", "workspace", "external-factor", "run", "job",
        "research", "agent-flow", "research-graph", "report",
        "research-evidence", "profile-agent", "trial-plan", "products",
        "custom_factors", "factor-library",
    ):
        assert f'"{command}"' in source

    for web_only in ("subordinates", "user_roles", "device_authorization"):
        assert f'"{web_only}"' in source
