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
    navigation = (PROFILE_UI / "ResearchReportTreeNavigation.swift").read_text()

    assert "focusedComponentID" in source
    assert "prefetch" in source
    assert "NSCache<NSURL, NSDictionary>" in loader
    assert "focusedComponentID" in view
    assert "ResearchReportTreeNavigation.neighbors" in view
    assert "static func neighbors" in navigation
    assert "Task.sleep" not in view


def test_structured_components_keep_lazy_rendering_and_wrapped_chips() -> None:
    component = (PROFILE_UI / "ResearchDocumentComponentView.swift").read_text()
    chips = (PROFILE_UI / "ResearchDocumentBindingChipsView.swift").read_text()

    assert "DisclosureGroup" in component
    assert "ResearchDocumentBindingChipsView" in component
    assert ".frame(maxHeight: 260)" in component
    assert "ResearchDocumentChipFlowLayout: Layout" in chips
    assert ".frame(width:" not in chips


def test_research_tree_never_collapses_unrelated_branches_onto_one_lane() -> None:
    tree = (PROFILE_UI / "ResearchVersionTreePane.swift").read_text()

    assert "private var visibleBranches" in tree
    assert "workPackage.omittedBranchCount" in tree
    assert "hiddenBranchCount" in tree
    assert 'L10n.format("另有 %lld 条分支"' in tree
    assert "return min(index, laneCount - 1)" not in tree
