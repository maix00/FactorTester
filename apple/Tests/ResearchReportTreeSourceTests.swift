import XCTest
@testable import FTClient

final class ResearchReportTreeSourceTests: XCTestCase {
    func testMissingFocusDefaultsToLatestChapter() async throws {
        let head = try makeReportTree()
        let authoring = head.deletingLastPathComponent()
        let root = try ResearchReportTreeNodeLoader.readNode(
            reference: nodeReference("root", hash: "a"), root: authoring
        )
        XCTAssertEqual(
            try ResearchReportTreeNodeLoader.outline(from: root, root: authoring)
                .map(\.id),
            ["first", "second"]
        )
        XCTAssertEqual(
            try ResearchReportTreeNodeLoader.loadSubtree(
                reference: nodeReference("second", hash: "c"),
                parentID: nil, root: authoring
            ).components.map(\.id),
            ["second"]
        )
        let payload = try await ResearchReportTreeSource.load(
            localRef: head.absoluteString,
            focusedComponentID: "missing",
            windowRadius: 0
        )

        XCTAssertEqual(payload.focusedComponentID, "second")
        XCTAssertEqual(payload.loadedComponentIDs, ["second"])
        XCTAssertEqual(payload.components.map(\.id), ["second"])
    }

    private func makeReportTree() throws -> URL {
        let authoring = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: authoring) }
        let rootRef = nodeReference("root", hash: "a")
        let firstRef = nodeReference("first", hash: "b")
        let secondRef = nodeReference("second", hash: "c")
        try write(node("root", kind: "root", children: [
            child("first", firstRef), child("second", secondRef),
        ]), reference: rootRef, under: authoring)
        try write(node("first", kind: "chapter"), reference: firstRef, under: authoring)
        try write(node("second", kind: "chapter"), reference: secondRef, under: authoring)
        let head: [String: Any] = [
            "schema_version": 2, "report_id": "report", "title": "报告",
            "language": "zh-Hans", "generation": 0, "root_ref": rootRef,
            "assets": [], "changed_node_ids": ["root"], "locator_generation": 0,
        ]
        let url = authoring.appendingPathComponent("HEAD.json")
        try JSONSerialization.data(withJSONObject: head).write(to: url)
        return url
    }

    private func node(
        _ id: String, kind: String, children: [[String: String]] = []
    ) -> [String: Any] {
        [
            "schema_version": 1, "node_id": id, "kind": kind,
            "title": id, "body": "", "content": NSNull(),
            "display_kind": "", "created_at": 0,
            "children": children, "bindings": [],
        ]
    }

    private func child(_ id: String, _ reference: String) -> [String: String] {
        ["node_id": id, "ref": reference]
    }

    private func nodeReference(_ id: String, hash: Character) -> String {
        "nodes/\(id)/\(String(repeating: String(hash), count: 64)).json"
    }

    private func write(
        _ value: [String: Any], reference: String, under root: URL
    ) throws {
        let url = reference.split(separator: "/").reduce(root) {
            $0.appendingPathComponent(String($1))
        }
        try FileManager.default.createDirectory(
            at: url.deletingLastPathComponent(), withIntermediateDirectories: true
        )
        try JSONSerialization.data(withJSONObject: value).write(to: url)
    }
}
