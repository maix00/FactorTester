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
    run_rows = _rule(css, ".test-workbench .test-run-field-rows")
    assert ".content:has(> .test-workbench)" in css
    assert "padding: 22px 36px 30px" in css
    assert "gap: var(--test-workbench-section-gap)" in workbench
    assert "--test-workbench-section-gap: 12px" in (
        (WEB_ROOT / "styles" / "app.css").read_text()
    )
    assert "font-size: 13px" in workbench
    assert "min-height: 39px" in settings and "padding: 2px 0" in settings
    assert "grid-template-columns: minmax(0, 1fr)" in run_rows
    for selector in (
        ".test-run-inputs",
        ".test-workbench .backtest-group-form",
        ".test-workbench .test-run-panel",
        ".job-detail",
        ".job-input-detail",
    ):
        _rule(css, selector)


def test_settings_manager_defaults_reset_the_chip_row_itself() -> None:
    css = (WEB_ROOT / "styles" / "task-inputs.css").read_text()
    row = _rule(css, ".test-workbench .test-settings-manager-row")
    row_list = _rule(css, ".test-workbench .test-settings-manager-list")
    row_body = _rule(css, ".test-workbench .test-settings-manager-row-body")
    defaults = _rule(
        css,
        ".test-workbench .test-settings-manager-defaults.backend-settings-chip-row",
    )
    defaults_shell = _rule(css, ".test-workbench .test-settings-manager-defaults")
    chip_group = _rule(
        css,
        ".test-workbench .test-settings-manager-defaults .backend-settings-chip-group",
    )
    chip = _rule(
        css,
        ".test-workbench .test-settings-manager-defaults .backend-setting-chip",
    )
    chip_label = _rule(
        css,
        ".test-workbench .test-settings-manager-defaults .backend-setting-chip-label",
    )
    assert "padding: 3px 0" in row
    assert "align-items: baseline" in row
    assert "align-items: baseline" in row_body
    assert "border-top" not in row
    assert "width: 100%" in row_list and "min-width: 0" in row_list
    assert "width: 100%" in row_body and "min-width: 0" in row_body
    assert "min-height: 0" in defaults
    assert "padding: 0" in defaults
    assert "width: 100%" in defaults_shell and "max-width: 100%" in defaults_shell
    assert "flex-wrap: wrap" in chip_group and "width: 100%" in chip_group
    assert "max-width: 100%" in chip and "box-sizing: border-box" in chip
    assert "white-space: nowrap" in chip
    assert "flex: 0 1 auto" in chip_label

    heading = _rule(css, ".test-workbench .test-settings-manager-section-heading")
    assert "display: flex" in heading and "align-items: center" in heading
    assert "min-height: 28px" in heading and "box-sizing: border-box" in heading
    checkbox = _rule(css, '.test-workbench .test-settings-manager-row input[type="checkbox"]')
    assert "transform: translateY(2px)" in checkbox


def test_settings_manager_uses_inline_chip_nodes_inside_label_rows() -> None:
    chips = (WEB_ROOT / "workbench" / "test-setting-chips.js").read_text()
    settings = (WEB_ROOT / "workbench" / "test-settings.js").read_text()
    assert 'options.inline === true' in chips
    assert 'document.createElement(inline ? "span" : "div")' in chips
    assert 'inline: true' in settings


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
