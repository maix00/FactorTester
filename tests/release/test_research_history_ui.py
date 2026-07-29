from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROFILE_UI = ROOT / "apple/Sources/Features/Profiles"


def test_active_research_reader_uses_branch_report_tree_only() -> None:
    model = (PROFILE_UI / "ResearchRecordModel.swift").read_text()
    detail = (PROFILE_UI / "ProfileLiveResearchDetail.swift").read_text()
    source = (PROFILE_UI / "ResearchDocumentSource.swift").read_text()

    assert "currentReportArtifact" in model
    assert "journalRef" not in model
    assert "indexRef" not in model
    assert "ResearchDocumentReportView" in detail
    assert "ResearchNarrativeReportView" not in detail
    assert '"schema_version"] as? Int == 2' in source
    assert '"root_ref"' in source
    assert "JOURNAL.json" not in source
    assert "DOCUMENT.json" not in source


def test_report_reader_loads_current_node_and_prefetches_neighbors() -> None:
    source = (PROFILE_UI / "ResearchDocumentSource.swift").read_text()
    loader = (PROFILE_UI / "ResearchReportTreeNodeLoader.swift").read_text()
    view = (PROFILE_UI / "ResearchDocumentReportView.swift").read_text()
    report_navigation = (
        PROFILE_UI / "ResearchDocumentReportNavigation.swift"
    ).read_text()
    navigation = (PROFILE_UI / "ResearchReportTreeNavigation.swift").read_text()
    observer = (PROFILE_UI / "ResearchReportTreeFileObserver.swift").read_text()

    assert "focusedComponentID" in source
    assert "prefetch" in source
    assert "NSCache<NSURL, NSDictionary>" in loader
    assert "focusedComponentID" in report_navigation
    assert "ResearchReportChapterWindow.loadedIDs" in source
    assert "ResearchReportChapterWindow.prefetchIDs" in report_navigation
    assert "static func neighbors" in navigation
    assert "Task.checkCancellation" in report_navigation
    assert "catch is CancellationError" in report_navigation
    assert "presentedItemURL = url.deletingLastPathComponent()" in observer
    assert "Task.sleep" not in view


def test_report_reader_retries_once_after_head_generation_changes() -> None:
    source = (PROFILE_UI / "ResearchDocumentSource.swift").read_text()

    assert "let first = try Metadata" in source
    assert "let retry = try Metadata" in source
    assert "retry.generation != first.generation" in source
    assert "return try loadPayload(\n                    retry" in source


def test_structured_components_render_only_explicit_typed_rich_text_links() -> None:
    component = (PROFILE_UI / "ResearchDocumentComponentView.swift").read_text()
    rich_text = (PROFILE_UI / "ResearchDocumentRichTextView.swift").read_text()
    inline_text = (
        PROFILE_UI / "ResearchDocumentInlineTextMac.swift"
    ).read_text()
    attributed = (
        PROFILE_UI / "ResearchInlineAttributedString.swift"
    ).read_text()
    links = (PROFILE_UI / "ResearchDocumentTypedLinks.swift").read_text()
    table = (PROFILE_UI / "ResearchDocumentTableView.swift").read_text()

    assert "ResearchReportSectionDisclosureHeader" in component
    assert "ResearchDocumentBindingChipsView" not in component
    assert "ResearchInlineAttributedString.make" in inline_text
    assert "scope.presentationSegments" in attributed
    assert "researchDocumentReferenceAction" in rich_text
    assert "factortester://" in links
    assert "maximumHeight: CGFloat = 420" in table
    assert not (PROFILE_UI / "ResearchDocumentBindingChipsView.swift").exists()


def test_research_report_uses_node_timeline_not_a_retired_version_tree() -> None:
    tree = PROFILE_UI / "ResearchVersionTreePane.swift"
    timeline = (PROFILE_UI / "ResearchReportNodeTimelineNavigator.swift").read_text()
    tooltip = (PROFILE_UI / "ResearchReportNodeRailTooltip.swift").read_text()

    assert not tree.exists()
    assert "LazyVStack" in timeline
    assert "selectedComponentID" in timeline
    assert "graphVersion" in tooltip
