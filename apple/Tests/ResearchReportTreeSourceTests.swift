import XCTest
@testable import FTClient

final class ResearchReportTreeSourceTests: XCTestCase {
    func testRejectsPreviousReportStorageSchema() async throws {
        let headURL = try makeReportTree()
        var head = try XCTUnwrap(
            JSONSerialization.jsonObject(with: Data(contentsOf: headURL))
                as? [String: Any]
        )
        head["schema_version"] = 2
        try JSONSerialization.data(withJSONObject: head).write(to: headURL)

        do {
            _ = try await ResearchReportTreeSource.load(
                localRef: headURL.absoluteString,
                focusedComponentID: nil
            )
            XCTFail("previous report storage schema must be rejected")
        } catch ResearchReportTreeSourceError.invalidHead {
            // Expected: an older client cannot read or mutate schema 3 storage.
        }
    }

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
            focusedComponentID: "missing"
        )

        XCTAssertEqual(payload.focusedComponentID, "second")
        XCTAssertEqual(payload.loadedComponentIDs, ["second"])
        XCTAssertEqual(payload.components.map(\.id), ["second"])
        XCTAssertEqual(payload.outline.map(\.componentID), ["first", "second"])
    }

    func testChapterCacheEvictsLeastRecentlyUsedSubtrees() {
        let reportPath = "/tmp/\(UUID().uuidString)/HEAD.json"
        defer {
            ResearchReportTreeNodeCache.shared.retainCurrentGeneration(
                reportPath: reportPath,
                generation: 1
            )
        }
        for index in 0..<30 {
            var state = ResearchReportTreeNodeLoader.TreeState()
            state.components = [component("chapter-\(index)")]
            ResearchReportTreeNodeCache.shared.insert(
                state,
                reportPath: reportPath,
                generation: 0,
                reference: "chapter-\(index)"
            )
        }

        XCTAssertNil(ResearchReportTreeNodeCache.shared.value(
            reportPath: reportPath,
            generation: 0,
            reference: "chapter-0"
        ))
        XCTAssertEqual(
            ResearchReportTreeNodeCache.shared.value(
                reportPath: reportPath,
                generation: 0,
                reference: "chapter-29"
            )?.components.map(\.id),
            ["chapter-29"]
        )
    }

    func testOutlineCacheIsScopedToTheVisibleGeneration() {
        let reportPath = "/tmp/\(UUID().uuidString)/HEAD.json"
        let reference = "nodes/root/root.json"
        ResearchReportTreeNodeCache.shared.insertOutline(
            ResearchReportTreeOutline(
                items: [.init(id: "chapter", reference: "chapter-ref")],
                details: []
            ),
            reportPath: reportPath,
            generation: 0,
            reference: reference
        )
        XCTAssertEqual(
            ResearchReportTreeNodeCache.shared.outline(
                reportPath: reportPath,
                generation: 0,
                reference: reference
            )?.items.map(\.id),
            ["chapter"]
        )

        ResearchReportTreeNodeCache.shared.retainCurrentGeneration(
            reportPath: reportPath,
            generation: 1
        )
        XCTAssertNil(ResearchReportTreeNodeCache.shared.outline(
            reportPath: reportPath,
            generation: 0,
            reference: reference
        ))
    }

    func testLoadsEverySupportedComponentContentWithoutDroppingTheChapter() async throws {
        let authoring = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: authoring) }
        let componentKinds: [(String, String, Any)] = [
            ("text", "entry", "正文"),
            ("code", "entry", ["code": "x = 1", "language": "python"]),
            ("math", "special", ["latex": #"x^2"#, "fallback": "x squared"]),
            ("table", "table", [
                "columns": ["指标", "值"],
                "rows": [["收益", #"\\(r_t\\)"#]],
            ]),
            ("image", "entry", ["asset_ref": "asset:chart"]),
            ("json", "result", ["metric": 1]),
        ]
        let childRefs = componentKinds.enumerated().map { index, item in
            nodeReference(item.0, hash: Character(String(index + 2)))
        }
        let chapterRef = nodeReference("chapter", hash: "b")
        let rootRef = nodeReference("root", hash: "a")
        try write(node("root", kind: "root", children: [
            child("chapter", chapterRef),
        ]), reference: rootRef, under: authoring)
        try write(node("chapter", kind: "chapter", children:
            zip(componentKinds, childRefs).map { child($0.0.0, $0.1) }
        ), reference: chapterRef, under: authoring)
        for ((id, kind, content), reference) in zip(componentKinds, childRefs) {
            try write(
                node(id, kind: kind, content: content),
                reference: reference,
                under: authoring
            )
        }
        let head: [String: Any] = [
            "schema_version": 3, "report_id": "report", "title": "报告",
            "language": "zh-Hans", "generation": 0, "root_ref": rootRef,
            "assets": [[
                "asset_ref": "asset:chart", "filename": "equity.png",
                "media_type": "image/png",
            ]],
            "changed_node_ids": ["root"], "locator_generation": 0,
        ]
        let headURL = authoring.appendingPathComponent("HEAD.json")
        try JSONSerialization.data(withJSONObject: head).write(to: headURL)

        let payload = try await ResearchReportTreeSource.load(
            localRef: headURL.absoluteString,
            focusedComponentID: "chapter"
        )

        XCTAssertEqual(payload.components.map(\.id), [
            "chapter", "text", "code", "math", "table", "image", "json",
        ])
        XCTAssertEqual(payload.assets.map(\.filename), ["equity.png"])
        XCTAssertEqual(payload.components.compactMap(contentKind), [
            "none", "text", "code", "math", "table", "image", "json",
        ])
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
        try write(
            node("first", kind: "chapter", bindings: [
                binding("evidence:first"),
            ]), reference: firstRef, under: authoring
        )
        try write(
            node("second", kind: "chapter", bindings: [
                binding("evidence:second"),
            ]), reference: secondRef, under: authoring
        )
        let head: [String: Any] = [
            "schema_version": 3, "report_id": "report", "title": "报告",
            "language": "zh-Hans", "generation": 0, "root_ref": rootRef,
            "assets": [], "changed_node_ids": ["root"], "locator_generation": 0,
        ]
        let url = authoring.appendingPathComponent("HEAD.json")
        try JSONSerialization.data(withJSONObject: head).write(to: url)
        return url
    }

    private func node(
        _ id: String, kind: String, children: [[String: String]] = [],
        bindings: [[String: Any]] = [], content: Any = NSNull()
    ) -> [String: Any] {
        [
            "schema_version": 1, "node_id": id, "kind": kind,
            "title": id, "body": "", "content": content,
            "display_kind": "", "created_at": 0,
            "children": children, "bindings": bindings,
        ]
    }

    private func binding(_ reference: String) -> [String: Any] {
        [
            "binding_id": reference.replacingOccurrences(of: ":", with: "-"),
            "kind": "evidence", "target_ref": reference,
            "label": "节点", "data": [:],
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

    private func contentKind(_ component: ResearchDocumentComponent) -> String {
        switch component.content {
        case .none: return "none"
        case .text: return "text"
        case .code: return "code"
        case .math: return "math"
        case .list: return "list"
        case .table: return "table"
        case .image: return "image"
        case .json: return "json"
        }
    }

    private func component(_ id: String) -> ResearchDocumentComponent {
        ResearchDocumentComponent(
            id: id,
            kind: "chapter",
            displayKind: "",
            parentID: nil,
            title: id,
            body: "",
            content: .none
        )
    }
}
