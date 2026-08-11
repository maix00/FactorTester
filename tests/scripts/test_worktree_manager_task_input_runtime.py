"""Executable browser-module contracts for retained Job inputs."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WEB_ROOT = ROOT / "scripts" / "worktree_manager_web"


def _run_node(source: str) -> dict[str, object]:
    completed = subprocess.run(
        ["node", "-e", source],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_dependency_upload_freezes_purpose_path_and_analysis_scope() -> None:
    module = WEB_ROOT / "workbench" / "test-source-upload.js"
    result = _run_node(f"""
      global.window = {{}};
      global.FTTestInputState = {{
        putDependency(state, value) {{ state.saved = value; }},
      }};
      require({json.dumps(str(module))});
      const context = {{t(value) {{ return value; }}}};
      const state = {{}};
      const file = {{name: "risk-limits.yaml", async text() {{
        return "target: 0.4\\nmaximum: 0.5\\n";
      }}}};
      window.FTTestSourceUpload.importDependency(
        context, state, file, "strategy_configuration",
      ).then(() => process.stdout.write(JSON.stringify(state.saved)));
    """)
    assert result == {
        "path": "strategy-configs/risk-limits.yaml",
        "content": "target: 0.4\nmaximum: 0.5\n",
        "content_type": "application/yaml",
        "title_zh": "策略配置：risk-limits.yaml",
        "purpose": "strategy_configuration",
        "analyses": ["backtest"],
    }


def test_strategy_hook_inspection_sends_source_and_retains_normalized_value() -> None:
    module = WEB_ROOT / "workbench" / "test-source-upload.js"
    result = _run_node(f"""
      global.window = {{}};
      global.FTTestInputState = {{
        putStrategy(state, source, inspection) {{
          state.saved = {{source, inspection}};
        }},
      }};
      require({json.dumps(str(module))});
      const requests = [];
      const context = {{
        t(value) {{ return value; }},
        servicePath(path) {{ return path; }},
        async api(path, options) {{
          requests.push({{path, body: JSON.parse(options.body)}});
          return {{valid: true, entrypoint: "RiskGate", callbacks: ["on_bar"]}};
        }},
      }};
      const state = {{}};
      const file = {{name: "risk_gate.py", async text() {{
        return "class RiskGate:\\n    pass\\n";
      }}}};
      window.FTTestSourceUpload.inspectStrategy(context, state, file)
        .then(() => process.stdout.write(JSON.stringify({{
          request: requests[0], saved: state.saved,
        }})));
    """)
    assert result["request"]["path"] == "/api/run-inputs/strategy/inspect"
    assert result["request"]["body"] == {
        "path": "strategies/risk_gate.py",
        "source_code": "class RiskGate:\n    pass\n",
        "strategy_spec": None,
    }
    assert result["saved"]["source"]["path"] == "strategies/risk_gate.py"
    assert result["saved"]["inspection"]["entrypoint"] == "RiskGate"


def test_download_all_preserves_input_paths_and_output_file_names() -> None:
    module = WEB_ROOT / "jobs" / "artifacts.js"
    result = _run_node(f"""
      global.window = {{}};
      require({json.dumps(str(module))});
      const input = window.FTJobArtifacts.artifactDownloadParts({{
        role: "input", artifact_kind: "run_dependency",
        logical_path: "strategies/alpha/risk-limits.yaml",
        file_name: "risk-limits.yaml",
      }});
      const output = window.FTJobArtifacts.artifactDownloadParts({{
        role: "output", file_name: "equity-curve.svg",
      }});
      process.stdout.write(JSON.stringify({{input, output}}));
    """)
    assert result["input"] == [
        "inputs", "run_dependency", "strategies", "alpha",
        "risk-limits.yaml",
    ]
    assert result["output"] == ["equity-curve.svg"]
