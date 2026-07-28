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
    # The disclosure control is now a reusable localized header so the Swift
    # viewer can keep the same collapsed semantics in every locale.
    assert "ResearchReportSectionDisclosureHeader" in view
    assert "沿用义务" in view
    assert "ResearchCheckpointCard" not in view
    assert "journalRef" in model
    assert "journalHash" in model
    assert "MarkdownUI" not in view
    assert "WKWebView" not in view


def test_legacy_fallback_does_not_present_index_summary_as_complete_report() -> None:
    view = (PROFILE_UI / "ResearchNarrativeReportView.swift").read_text()

    assert "没有经过校验的中文 journal" in view
    assert "不会用旧 REPORT.md 或 INDEX.json 冒充完整报告" in view


def test_narrative_page_appends_structured_source_without_polling() -> None:
    narrative = (PROFILE_UI / "ResearchNarrativeReportView.swift").read_text()
    document = (PROFILE_UI / "ResearchDocumentReportView.swift").read_text()
    source = (PROFILE_UI / "ResearchDocumentSource.swift").read_text()

    assert "ResearchDocumentSupplementView" in narrative
    assert "documentArtifact" in narrative
    assert "ResearchDocumentFileObserver" in document
    assert "Task.sleep(nanoseconds: 2_000_000_000)" not in document
    assert "NSFileCoordinator.addFilePresenter" in source
    assert "NSFileCoordinator.removeFilePresenter" in source


def test_structured_components_render_local_bindings_as_wrapped_chips() -> None:
    source = (PROFILE_UI / "ResearchDocumentSource.swift").read_text()
    component = (PROFILE_UI / "ResearchDocumentComponentView.swift").read_text()
    chips = (PROFILE_UI / "ResearchDocumentBindingChipsView.swift").read_text()

    assert 'appendingPathComponent("BINDINGS.json")' in source
    assert "presentedItemURL" in source
    assert "deletingLastPathComponent" in source
    assert "presentedSubitemDidChange" in source
    assert "ResearchDocumentBindingChipsView" in component
    assert "ResearchDocumentChipFlowLayout: Layout" in chips
    assert 'case "evidence"' in chips
    assert 'case "job"' in chips
    assert ".frame(width:" not in chips


def test_research_tree_never_collapses_unrelated_branches_onto_one_lane() -> None:
    tree = (PROFILE_UI / "ResearchVersionTreePane.swift").read_text()

    assert "private var visibleBranches" in tree
    assert "workPackage.omittedBranchCount" in tree
    assert "hiddenBranchCount" in tree
    assert 'L10n.format("另有 %lld 条分支"' in tree
    assert "return min(index, laneCount - 1)" not in tree
