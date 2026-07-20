from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROFILE_UI = ROOT / "apple/Sources/Features/Profiles"


def test_research_history_uses_bounded_structured_sidecar() -> None:
    index = (PROFILE_UI / "ResearchReportIndex.swift").read_text()
    view = (
        PROFILE_UI / "ResearchStructuredDetailView.swift"
    ).read_text()
    model = (PROFILE_UI / "ResearchRecordModel.swift").read_text()

    assert "512 * 1024" in index
    assert "maximumSections = 100" in index
    assert "maximumSummaryCharacters = 1_000" in index
    assert 'root["sections"]' in index
    assert "Data(contentsOf: url)" in index
    assert "artifact.localRef" not in index
    assert "indexRef" in model
    assert "ResearchStructuredDetailView" in view
    assert "selectedStep" in view
    assert "relatedSections" in view
    assert "referenceCards" in view
    assert 'Button("View original report")' in view
    assert "MarkdownUI" not in view
    assert "WKWebView" not in view


def test_legacy_fallback_does_not_scan_complete_markdown() -> None:
    index = (PROFILE_UI / "ResearchReportIndex.swift").read_text()

    assert "fallback(artifact: artifact)" in index
    assert "artifact.sectionRefs" in index
    assert "maximumSections" in index
    assert ".md" not in index
