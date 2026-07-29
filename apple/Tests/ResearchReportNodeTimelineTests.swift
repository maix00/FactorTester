import XCTest
@testable import FTClient

final class ResearchReportNodeTimelineTests: XCTestCase {
    func testUsesOnlyCurrentBranchNodeChaptersInSequence() throws {
        let items = ResearchReportNodeTimelineBuilder.items(
            detail: try detail(), workPackage: try workPackage(), steps: [],
            artifact: artifact()
        )

        XCTAssertEqual(items.map(\.componentID), ["chapter-one", "chapter-two"])
        XCTAssertEqual(items.map(\.graphVersion), ["v9", "v10"])
    }

    func testReportOutlineIncludesInheritedBranchNodesWithoutSectionRefs() throws {
        let items = ResearchReportNodeTimelineBuilder.items(
            detail: try detail(), workPackage: try workPackage(), steps: [],
            artifact: artifact(),
            reportOutline: [
                outline("chapter-one", "trace:one"),
                outline("chapter-other", "trace:other"),
                outline("chapter-two", "trace:two"),
            ]
        )

        XCTAssertEqual(items.map(\.componentID), [
            "chapter-one", "chapter-other", "chapter-two",
        ])
        XCTAssertEqual(items.map(\.title), ["one", "other", "two"])
        XCTAssertEqual(items.map(\.graphVersion), ["v9", "v9", "v10"])
    }

    func testOpensCurrentHeadChapterBeforeEarlierChapters() throws {
        let detail = try detail()
        let package = try workPackage()
        let artifact = artifact()
        let items = ResearchReportNodeTimelineBuilder.items(
            detail: detail, workPackage: package, steps: [], artifact: artifact
        )

        XCTAssertEqual(
            ResearchReportNodeTimelineBuilder.initialComponentID(
                detail: detail, workPackage: package, steps: [],
                artifact: artifact, items: items
            ),
            "chapter-two"
        )
    }

    func testFollowsAnAppendedChapterOnlyFromPreviousHead() {
        XCTAssertEqual(
            ResearchReportHeadFollow.nextChapter(
                previousOutline: ["one", "two"], selectedID: "two",
                centeredID: "two", newOutline: ["one", "two", "three"]
            ),
            "three"
        )
        XCTAssertNil(
            ResearchReportHeadFollow.nextChapter(
                previousOutline: ["one", "two"], selectedID: "one",
                centeredID: "one", newOutline: ["one", "two", "three"]
            )
        )
    }

    private func detail() throws -> ProfileResearchDetail {
        try decode("""
        {"research_ref":"research:r","work_package_ref":"work-package:r",
        "branch_ref":"graph-branch:instance:main","label":"研究",
        "current_node":"two","status":"running","latest_trace_ref":"trace:two",
        "evidence_refs":[],"omitted_evidence_count":0,
        "research_cycle":{"claims":[],"obligations":[]},"job_refs":[],"run_refs":[],
        "timeline_href":"","refresh":{"mode":"manual","terminal":false},"etag":"1"}
        """)
    }

    private func workPackage() throws -> ProfileResearchWorkPackageDetail {
        try decode("""
        {"research_ref":"research:r","work_package_ref":"work-package:r",
        "product_group":"","mode":"","branch_count":1,"omitted_branch_count":0,
        "branches":[],"etag":"1","tree":{"schema_version":1,"edges":[],
        "omitted_node_count":0,"nodes":[
        {"node_ref":"one","checkpoint_ref":"trace:one","branch_ref":"graph-branch:instance:main","navigation_branch_id":"main","graph_ref":"factor@v9","edge_ref":"a","from_node":"root","to_node":"one","created_at":1,"status":"completed","is_head":false,"is_root":true,"sequence_rank":1,"history_rank":1},
        {"node_ref":"two","checkpoint_ref":"trace:two","branch_ref":"graph-branch:instance:main","navigation_branch_id":"main","graph_ref":"factor@v10","edge_ref":"b","from_node":"one","to_node":"two","created_at":2,"status":"running","is_head":true,"is_root":false,"sequence_rank":2,"history_rank":2},
        {"node_ref":"other","checkpoint_ref":"trace:other","branch_ref":"graph-branch:instance:other","navigation_branch_id":"other","graph_ref":"factor@v9","edge_ref":"c","from_node":"root","to_node":"other","created_at":3,"status":"running","is_head":true,"is_root":false,"sequence_rank":3,"history_rank":3}]}}
        """)
    }

    private func artifact() -> ResearchArtifactModel {
        ResearchArtifactModel(json: [
            "artifact_ref": "artifact:report", "format": "report_tree",
            "local_ref": "file:///report", "section_refs": [
                ["link_id": "1", "kind": "report_section",
                 "target_ref": "trace:one", "section_ref": "chapter-one"],
                ["link_id": "2", "kind": "report_section",
                 "target_ref": "trace:two", "section_ref": "chapter-two"],
                ["link_id": "3", "kind": "report_section",
                 "target_ref": "trace:other", "section_ref": "chapter-other"],
            ],
        ])
    }

    private func outline(
        _ componentID: String, _ reference: String
    ) -> ResearchReportOutlineItem {
        ResearchReportOutlineItem(
            componentID: componentID, title: "历史节点",
            fallbackTitle: "历史节点说明", createdAt: 0,
            references: [reference]
        )
    }

    private func decode<T: Decodable>(_ json: String) throws -> T {
        try JSONDecoder().decode(T.self, from: Data(json.utf8))
    }
}
