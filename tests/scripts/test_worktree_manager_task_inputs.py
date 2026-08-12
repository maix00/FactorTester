"""UI contracts for compact, source-backed test tasks."""

from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WEB_ROOT = ROOT / "server" / "manager" / "web"


def _rule(css: str, selector: str) -> str:
    match = re.search(rf"{re.escape(selector)}\s*\{{([^}}]+)\}}", css)
    assert match is not None, selector
    return match.group(1)


def test_task_density_overrides_load_last_and_cover_every_task_surface() -> None:
    manifest = json.loads((WEB_ROOT / "module-manifest.json").read_text())
    assert manifest["styles"][-1] == "styles/task-inputs.css"

    css = (WEB_ROOT / "styles" / "task-inputs.css").read_text()
    workbench = _rule(css, ".test-workbench")
    settings = _rule(css, ".test-workbench .test-setting-row")
    assert "gap: 6px" in workbench and "font-size: 13px" in workbench
    assert "min-height: 39px" in settings and "padding: 2px 0" in settings
    for selector in (
        ".test-run-inputs",
        ".test-workbench .backtest-group-form",
        ".test-workbench .test-run-panel",
        ".job-detail",
        ".job-input-detail",
    ):
        _rule(css, selector)


def test_backtest_source_panel_covers_executable_and_retained_inputs() -> None:
    source = (WEB_ROOT / "workbench" / "test-source-upload.js").read_text()
    contracts = (ROOT / "tools" / "testers" / "run_input_contracts.py").read_text()
    for label in (
        "上传策略 Hook",
        "导入策略配置",
        "添加依赖文件",
        "提交后作为任务输入保留，清空任务文件时一并删除",
    ):
        assert label in contracts
    for purpose in (
        "strategy_dependency",
        "strategy_configuration",
        "run_configuration",
        "data_mapping",
        "documentation",
    ):
        assert purpose in contracts
    assert "contentOptions.inputs" in source
    assert "descriptor.label" in source
    assert "descriptor.description" in source
    assert "descriptor.purposes" in source


def test_embedded_client_uses_native_picker_for_the_same_web_upload_contract() -> None:
    source_path = (
        ROOT / "apple" / "Sources" / "Features" / "Web" / "WebPageView.swift"
    )
    source = source_path.read_text()
    assert "runOpenPanelWith parameters: WKOpenPanelParameters" in source
    assert "let panel = NSOpenPanel()" in source
    assert "panel.allowsMultipleSelection = parameters.allowsMultipleSelection" in source


def test_job_detail_combines_retained_inputs_and_outputs_for_download_all() -> None:
    source = (WEB_ROOT / "jobs" / "detail.js").read_text()
    assert "activeArtifactList()" in source
    assert "下载全部任务文件" in source
    assert "input_artifacts" in source
    assert "artifacts" in source
