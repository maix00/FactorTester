import XCTest
@testable import FTClient

final class ResearchReportTreeNodeLoaderTests: XCTestCase {
    func testOutlineAcceptsChapterAtRoot() throws {
        let root = try temporaryAuthoringRoot(kind: "chapter")
        let outline = try ResearchReportTreeNodeLoader.outline(
            from: reportRoot(), root: root
        )

        XCTAssertEqual(outline.map(\.id), ["chapter"])
    }

    func testOutlineRejectsNonChapterAtRoot() throws {
        let root = try temporaryAuthoringRoot(kind: "entry")

        XCTAssertThrowsError(
            try ResearchReportTreeNodeLoader.outline(from: reportRoot(), root: root)
        )
    }

    private func reportRoot() -> [String: Any] {
        [
            "schema_version": 1,
            "node_id": "root",
            "kind": "root",
            "children": [[
                "node_id": "chapter",
                "ref": "nodes/chapter/\(String(repeating: "a", count: 64)).json",
            ]],
        ]
    }

    private func temporaryAuthoringRoot(kind: String) throws -> URL {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        let file = root
            .appendingPathComponent("nodes/chapter", isDirectory: true)
            .appendingPathComponent("\(String(repeating: "a", count: 64)).json")
        try FileManager.default.createDirectory(
            at: file.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        let value: [String: Any] = ["node_id": "chapter", "kind": kind]
        try JSONSerialization.data(withJSONObject: value).write(to: file)
        addTeardownBlock { try? FileManager.default.removeItem(at: root) }
        return root
    }
}
