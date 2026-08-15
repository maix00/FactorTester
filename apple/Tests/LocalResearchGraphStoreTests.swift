import Foundation
import XCTest
@testable import FTClient

@MainActor
final class LocalResearchGraphStoreTests: XCTestCase {
    func testImportsManagesAndSelectsLocalYamlWithoutServerMetadata() throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
        let source = root.appendingPathComponent("source")
        let library = root.appendingPathComponent("library")
        try FileManager.default.createDirectory(
            at: source,
            withIntermediateDirectories: true
        )
        defer { try? FileManager.default.removeItem(at: root) }
        let yaml = """
        graph_id: local-graph
        version: 1
        """
        let sourceURL = source.appendingPathComponent("my graph.yaml")
        try Data(yaml.utf8).write(to: sourceURL)

        let store = LocalResearchGraphStore(root: library)
        store.importFile(from: sourceURL)

        let file = try XCTUnwrap(store.files.first)
        XCTAssertTrue(file.filename.hasSuffix(".yaml"))
        XCTAssertNil(store.defaultFile)
        XCTAssertTrue(store.errorMessage == nil)

        store.setDefault(file)
        XCTAssertEqual(store.defaultFile?.id, file.id)
        XCTAssertEqual(store.defaultGraphURL?.lastPathComponent, "\(file.id)-\(file.filename)")

        let index = try String(
            contentsOf: library.appendingPathComponent("index.json"),
            encoding: .utf8
        )
        XCTAssertFalse(index.contains("locale"))

        store.delete(file)
        XCTAssertTrue(store.files.isEmpty)
        XCTAssertNil(store.defaultFile)
    }
}
