from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROFILE_UI = ROOT / "apple/Sources/Features/Profiles"


def test_research_history_uses_verified_chinese_journal_as_primary_reading_view() -> None:
    journal = (PROFILE_UI / "ResearchJournal.swift").read_text()
    view = (PROFILE_UI / "ResearchNarrativeReportView.swift").read_text()
    model = (PROFILE_UI / "ResearchRecordModel.swift").read_text()

    assert "maximumBytes = 4 * 1024 * 1024" in journal
    assert 'value.language == "zh-Hans"' in journal
    assert "SHA256.hash" in journal
    assert "artifact.journalHash" in journal
    assert "ResearchNarrativeReportView" in view
    assert "ScrollViewReader" in view
    assert "reportParagraph(section.body, linkIDs: [], section: section)" in view
    assert "auditChip" in view
    assert ".popover(item:" in view
    assert "ResearchVersionTreePane" in view
    assert 'DisclosureGroup("沿用义务' in view
    assert "ResearchCheckpointCard" not in view
    assert "journalRef" in model
    assert "journalHash" in model
    assert "MarkdownUI" not in view
    assert "WKWebView" not in view


def test_legacy_fallback_does_not_present_index_summary_as_complete_report() -> None:
    view = (PROFILE_UI / "ResearchNarrativeReportView.swift").read_text()

    assert "没有经过校验的中文 journal" in view
    assert "不会用旧 REPORT.md 或 INDEX.json 冒充完整报告" in view


def test_research_tree_never_collapses_unrelated_branches_onto_one_lane() -> None:
    tree = (PROFILE_UI / "ResearchVersionTreePane.swift").read_text()

    assert "private var visibleBranches" in tree
    assert "workPackage.omittedBranchCount" in tree
    assert 'Text("另有 \\(hiddenBranchCount) 条分支")' in tree
    assert "return min(index, laneCount - 1)" not in tree
