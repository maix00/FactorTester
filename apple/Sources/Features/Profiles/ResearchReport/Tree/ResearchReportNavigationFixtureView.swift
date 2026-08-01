#if DEBUG
import Foundation
import SwiftUI

/// A deterministic, server-free reader fixture used by the macOS UI tests.
/// It exercises the real report source, bounded chapter window, navigation
/// rail, and programmatic scrolling instead of duplicating their state logic.
struct ResearchReportNavigationFixtureView: View {
    private let fixture: ResearchReportNavigationFixture?
    private let preparationError: String?

    init() {
        do {
            fixture = try ResearchReportNavigationFixture.make()
            preparationError = nil
        } catch {
            fixture = nil
            preparationError = error.localizedDescription
        }
    }

    var body: some View {
        if let fixture {
            ResearchDocumentReportView(
                detail: fixture.detail,
                workPackage: fixture.workPackage,
                steps: [],
                profileID: "maxa",
                profileName: "MaxA",
                reportTitle: "研究节点导航验收",
                artifact: fixture.artifact,
                serverURL: URL(string: "http://127.0.0.1")!,
                tabSession: ResearchReportTabSession(),
                openJob: { _ in },
                openProfile: { _, _ in }
            )
        } else {
            Text(preparationError ?? "fixture preparation failed")
                .accessibilityIdentifier("research.fixture.error")
        }
    }
}

private struct ResearchReportNavigationFixture {
    let detail: ProfileResearchDetail
    let workPackage: ProfileResearchWorkPackageDetail
    let artifact: ResearchArtifactModel

    static func make() throws -> Self {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent(
                "factortester-report-navigation-fixture",
                isDirectory: true
            )
        try? FileManager.default.removeItem(at: directory)
        try FileManager.default.createDirectory(
            at: directory,
            withIntermediateDirectories: true
        )

        let chapterIDs = (1...18).map { "chapter-\($0)" }
        let hashDigits = Array("123456789abcdef0")
        let rootRef = reference(id: "root", digit: "f")
        let chapterRefs = Dictionary(uniqueKeysWithValues:
            chapterIDs.enumerated().map { offset, id in
                (
                    id,
                    reference(
                        id: id,
                        digit: String(hashDigits[offset % hashDigits.count])
                    )
                )
            }
        )
        let listID = "chapter-18-list"
        let listRef = reference(id: listID, digit: "a")
        try write(
            node(
                id: "root",
                kind: "root",
                children: chapterIDs.map {
                    ["node_id": $0, "ref": chapterRefs[$0]!]
                }
            ),
            reference: rootRef,
            under: directory
        )
        for (offset, id) in chapterIDs.enumerated() {
            let number = offset + 1
            let paragraphs = (1...7).map {
                "节点 \(number) 的第 \($0) 段研究记录，用于验证连续滚动、"
                    + "相邻章节预加载和稳定的阅读位置。"
            }.joined(separator: "\n\n")
            try write(
                node(
                    id: id,
                    kind: "chapter",
                    title: "研究节点 \(number)",
                    body: paragraphs,
                    createdAt: Double(number),
                    children: number == 18
                        ? [["node_id": listID, "ref": listRef]] : [],
                    bindings: [[
                        "binding_id": "binding-\(number)",
                        "kind": "checkpoint",
                        "target_ref": "node:\(id)",
                        "label": "研究节点 \(number)",
                        "data": [:],
                    ]]
                ),
                reference: chapterRefs[id]!,
                under: directory
            )
        }
        try write(
            node(
                id: listID,
                kind: "entry",
                title: "列表",
                body: (1...5).map { "- 验收列表第 \($0) 项" }
                    .joined(separator: "\n"),
            createdAt: 18
            ),
            reference: listRef,
            under: directory
        )

        let head: [String: Any] = [
            "schema_version": 2,
            "report_id": "navigation-fixture",
            "title": "研究节点导航验收",
            "language": "zh-Hans",
            "generation": 1,
            "root_ref": rootRef,
            "assets": [],
            "changed_node_ids": chapterIDs,
            "locator_generation": 1,
        ]
        let headURL = directory.appendingPathComponent("HEAD.json")
        try JSONSerialization.data(withJSONObject: head).write(to: headURL)

        return try Self(
            detail: decode("""
            {"research_ref":"research:fixture",
            "work_package_ref":"work-package:fixture",
            "branch_ref":"graph-branch:fixture:main","label":"导航验收",
            "current_node":"chapter-18","status":"running",
            "latest_trace_ref":"node:chapter-18","evidence_refs":[],
            "omitted_evidence_count":0,
            "research_cycle":{"claims":[],"obligations":[]},
            "job_refs":[],"run_refs":[],"timeline_href":"",
            "refresh":{"mode":"manual","terminal":false},"etag":"1"}
            """),
            workPackage: decode("""
            {"research_ref":"research:fixture",
            "work_package_ref":"work-package:fixture","product_group":"",
            "mode":"","branch_count":1,"omitted_branch_count":0,
            "branches":[],"etag":"1"}
            """),
            artifact: ResearchArtifactModel(json: [
                "artifact_ref": "artifact:navigation-fixture",
                "format": "report_tree",
                "status": "ready",
                "local_ref": headURL.absoluteString,
                "section_refs": [],
            ])
        )
    }

    private static func node(
        id: String,
        kind: String,
        title: String = "",
        body: String = "",
        createdAt: Double = 0,
        children: [[String: String]] = [],
        bindings: [[String: Any]] = []
    ) -> [String: Any] {
        [
            "schema_version": 1,
            "node_id": id,
            "kind": kind,
            "title": title.isEmpty ? id : title,
            "body": body,
            "content": NSNull(),
            "display_kind": "",
            "created_at": createdAt,
            "children": children,
            "bindings": bindings,
        ]
    }

    private static func reference(id: String, digit: String) -> String {
        "nodes/\(id)/\(String(repeating: digit, count: 64)).json"
    }

    private static func write(
        _ value: [String: Any],
        reference: String,
        under root: URL
    ) throws {
        let url = reference.split(separator: "/").reduce(root) {
            $0.appendingPathComponent(String($1))
        }
        try FileManager.default.createDirectory(
            at: url.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        try JSONSerialization.data(withJSONObject: value).write(to: url)
    }

    private static func decode<T: Decodable>(_ json: String) throws -> T {
        try JSONDecoder().decode(T.self, from: Data(json.utf8))
    }
}
#endif
