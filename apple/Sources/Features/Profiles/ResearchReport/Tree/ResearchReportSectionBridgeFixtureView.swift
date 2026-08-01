#if DEBUG
import Foundation
import SwiftUI
struct ResearchReportSectionBridgeFixtureView: View {
    private let fixture = try? ResearchReportSectionBridgeFixture.make()

    var body: some View {
        if let fixture {
            ResearchDocumentReportView(
                detail: fixture.detail,
                workPackage: fixture.workPackage,
                steps: [],
                profileID: "maxa",
                profileName: "MaxA",
                reportTitle: "研究小节桥状连接验收",
                artifact: fixture.artifact,
                serverURL: URL(string: "http://127.0.0.1")!,
                tabSession: ResearchReportTabSession(),
                openJob: { _ in },
                openProfile: { _, _ in }
            )
        } else {
            Text("bridge fixture preparation failed")
        }
    }
}
private struct ResearchReportSectionBridgeFixture {
    let detail: ProfileResearchDetail
    let workPackage: ProfileResearchWorkPackageDetail
    let artifact: ResearchArtifactModel
    static func make() throws -> Self {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("factortester-section-bridge-fixture")
        try? FileManager.default.removeItem(at: root)
        try FileManager.default.createDirectory(
            at: root, withIntermediateDirectories: true
        )
        let children: [FixtureSection] = [
            ("ordinary-before", "section", "", "普通小节内容默认展示"),
            ("special-before", "special", "external_review", "特殊小节内容点击后展示"),
            ("path-selection", "special", "path_selection", "研究路径选择内容"),
            ("special-after", "special", "grill_resolution", "路径后的特殊内容"),
            ("ordinary-after", "subsection", "", "路径后的普通内容默认展示"),
        ]
        let nested: [FixtureSection] = [
            ("nested-ordinary", "subsection", "", "嵌套普通内容默认展示"),
            ("nested-special", "special", "external_review", "嵌套特殊内容点击后展示"),
        ]
        let chapterRef = reference("chapter", "a")
        let childRefs = Dictionary(uniqueKeysWithValues: zip(
            children + nested, "bcdef12"
        ).map { ($0.0.0, reference($0.0.0, String($0.1))) })
        try write(node(
            id: "root", kind: "root",
            children: [["node_id": "chapter", "ref": chapterRef]]
        ), reference: reference("root", "f"), under: root)
        try write(node(
            id: "chapter", kind: "chapter", title: "桥状连接验收章节",
            children: children.map {
                ["node_id": $0.0, "ref": childRefs[$0.0]!]
            }
        ), reference: chapterRef, under: root)
        for child in children {
            try write(node(
                id: child.0, kind: child.1, title: title(child.0),
                body: child.3, displayKind: child.2,
                children: child.0 == "ordinary-before" ? nested.map {
                    ["node_id": $0.0, "ref": childRefs[$0.0]!]
                } : []
            ), reference: childRefs[child.0]!, under: root)
        }
        for child in nested {
            try write(node(
                id: child.0, kind: child.1, title: title(child.0),
                body: child.3, displayKind: child.2
            ), reference: childRefs[child.0]!, under: root)
        }
        let headURL = root.appendingPathComponent("HEAD.json")
        try JSONSerialization.data(withJSONObject: [
            "schema_version": 2,
            "report_id": "section-bridge-fixture",
            "title": "研究小节桥状连接验收",
            "language": "zh-Hans",
            "generation": 1,
            "root_ref": reference("root", "f"),
            "assets": [], "changed_node_ids": ["chapter"],
            "locator_generation": 1,
        ]).write(to: headURL)
        return try Self(
            detail: decode("""
            {"research_ref":"research:fixture","work_package_ref":"work-package:fixture",
            "branch_ref":"graph-branch:fixture:main","label":"桥状连接验收",
            "current_node":"chapter","status":"running","latest_trace_ref":"node:chapter",
            "evidence_refs":[],"omitted_evidence_count":0,"research_cycle":{"claims":[],"obligations":[]},
            "job_refs":[],"run_refs":[],"timeline_href":"","refresh":{"mode":"manual","terminal":false},"etag":"1"}
            """),
            workPackage: decode("""
            {"research_ref":"research:fixture","work_package_ref":"work-package:fixture",
            "product_group":"","mode":"","branch_count":1,"omitted_branch_count":0,
            "branches":[],"etag":"1"}
            """),
            artifact: ResearchArtifactModel(json: [
                "artifact_ref": "artifact:section-bridge-fixture",
                "format": "report_tree", "status": "ready",
                "local_ref": headURL.absoluteString, "section_refs": [],
            ])
        )
    }
    private static func title(_ id: String) -> String {
        [
            "ordinary-before": "普通小节",
            "special-before": "特殊小节",
            "path-selection": "研究路径选择",
            "special-after": "路径后特殊小节",
            "ordinary-after": "路径后普通小节",
            "nested-ordinary": "嵌套普通小节",
            "nested-special": "嵌套特殊小节",
        ][id]!
    }
    private static func node(
        id: String, kind: String, title: String = "", body: String = "",
        displayKind: String = "", children: [[String: String]] = []
    ) -> [String: Any] {
        ["schema_version": 1, "node_id": id, "kind": kind,
         "title": title.isEmpty ? id : title, "body": body,
         "content": NSNull(), "display_kind": displayKind,
         "created_at": 0, "children": children, "bindings": []]
    }
    private static func reference(_ id: String, _ digit: String) -> String {
        "nodes/\(id)/\(String(repeating: digit, count: 64)).json"
    }
    private static func write(
        _ value: [String: Any], reference: String, under root: URL
    ) throws {
        let url = reference.split(separator: "/").reduce(root) {
            $0.appendingPathComponent(String($1))
        }
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(),
                                                withIntermediateDirectories: true)
        try JSONSerialization.data(withJSONObject: value).write(to: url)
    }
    private static func decode<T: Decodable>(_ json: String) throws -> T {
        try JSONDecoder().decode(T.self, from: Data(json.utf8))
    }

    private typealias FixtureSection = (String, String, String, String)
}
#endif
