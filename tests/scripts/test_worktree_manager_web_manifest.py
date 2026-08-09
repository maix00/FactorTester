"""Contracts for the static Web renderer module manifest."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WEB_ROOT = ROOT / "scripts" / "worktree_manager_web"


def test_manifest_matches_html_script_order_and_files() -> None:
    manifest = json.loads((WEB_ROOT / "module-manifest.json").read_text(encoding="utf-8"))
    html = (WEB_ROOT / manifest["entry"]).read_text(encoding="utf-8")

    assert manifest["schema_version"] == 1
    assert manifest["scripts"]
    assert manifest["styles"] == ["research.css"]
    for relative in [*manifest["scripts"], *manifest["styles"]]:
        assert (WEB_ROOT / relative).is_file(), relative

    script_paths = [
        line.split('src="/research-static/', 1)[1].split('"', 1)[0]
        for line in html.splitlines()
        if 'src="/research-static/' in line and line.endswith("</script>")
    ]
    assert script_paths == [*manifest["external_scripts"], *manifest["scripts"]]
    assert 'href="/research-static/research.css"' in html
