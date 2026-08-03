from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROFILE_UI = ROOT / "apple/Sources/Features/Profiles"
REPORT_UI = PROFILE_UI / "ResearchReport"
DOCUMENT_UI = REPORT_UI / "Document"
INLINE_UI = REPORT_UI / "Inline"
TREE_UI = REPORT_UI / "Tree"


def test_active_research_reader_uses_branch_report_tree_only() -> None:
    model = (PROFILE_UI / "ResearchRecordModel.swift").read_text()
    detail = (PROFILE_UI / "ProfileLiveResearchDetail.swift").read_text()
    source = (DOCUMENT_UI / "ResearchDocumentSource.swift").read_text()

    assert "currentReportArtifact" in model
    assert "journalRef" not in model
    assert "indexRef" not in model
    assert "ResearchDocumentReportView" in detail
    assert "ResearchNarrativeReportView" not in detail
    assert '"schema_version"] as? Int == 3' in source
    assert '"root_ref"' in source
    assert "JOURNAL.json" not in source
    assert "DOCUMENT.json" not in source


def test_report_reader_loads_exactly_one_selected_chapter() -> None:
    source = (DOCUMENT_UI / "ResearchDocumentSource.swift").read_text()
    loader = (TREE_UI / "ResearchReportTreeNodeLoader.swift").read_text()
    view = (DOCUMENT_UI / "ResearchDocumentReportView.swift").read_text()
    report_navigation = (
        DOCUMENT_UI / "ResearchDocumentReportNavigation.swift"
    ).read_text()
    observer = (TREE_UI / "ResearchReportTreeFileObserver.swift").read_text()

    assert "focusedComponentID" in source
    assert "NSCache<NSURL, NSDictionary>" in loader
    assert "focusedComponentID" in report_navigation
    assert "let loadedIDs = focused.map { [$0.id] } ?? []" in source
    assert "windowRadius" not in source
    assert "prefetchIDs" not in report_navigation
    assert "Task.checkCancellation" in report_navigation
    assert "catch is CancellationError" in report_navigation
    assert "presentedItemURL = url.deletingLastPathComponent()" in observer
    assert "Task.sleep" not in view


def test_report_reader_retries_once_after_head_generation_changes() -> None:
    source = (DOCUMENT_UI / "ResearchDocumentSource.swift").read_text()

    assert "let first = try Metadata" in source
    assert "let retry = try Metadata" in source
    assert "retry.generation != first.generation" in source
    assert "return try loadPayload(\n                    retry" in source


def test_structured_components_render_only_explicit_typed_rich_text_links() -> None:
    component = (DOCUMENT_UI / "ResearchDocumentComponentView.swift").read_text()
    rich_text = (DOCUMENT_UI / "ResearchDocumentRichTextView.swift").read_text()
    inline_text = (
        DOCUMENT_UI / "ResearchDocumentInlineTextMac.swift"
    ).read_text()
    inline_coordinator = (
        DOCUMENT_UI / "ResearchDocumentInlineTextCoordinator.swift"
    ).read_text()
    attributed = (
        INLINE_UI / "ResearchInlineAttributedString.swift"
    ).read_text()
    links = (DOCUMENT_UI / "ResearchDocumentTypedLinks.swift").read_text()
    table = (DOCUMENT_UI / "ResearchDocumentTableView.swift").read_text()

    assert "ResearchReportSectionBridge" in component
    assert "ResearchDocumentBindingChipsView" not in component
    assert "ResearchDocumentInlineTextCoordinator" in inline_text
    assert "ResearchInlineAttributedString.make" in inline_coordinator
    assert "scope.presentationSegments" in attributed
    assert "researchDocumentReferenceAction" in rich_text
    assert "factortester://" in links
    assert "maximumHeight: CGFloat = 420" in table
    assert not (DOCUMENT_UI / "ResearchDocumentBindingChipsView.swift").exists()


def test_research_report_uses_node_timeline_not_a_retired_version_tree() -> None:
    tree = REPORT_UI / "ResearchVersionTreePane.swift"
    timeline = (TREE_UI / "ResearchReportNodeTimelineNavigator.swift").read_text()
    tooltip = (TREE_UI / "ResearchReportNodeRailTooltip.swift").read_text()

    assert not tree.exists()
    assert "LazyVStack" in timeline
    assert "selectedComponentID" in timeline
    assert "graphVersion" in tooltip
