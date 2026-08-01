import XCTest
@testable import FTClient

final class ResearchReportTreeFileObserverTests: XCTestCase {
    func testObservesAuthoringDirectoryRatherThanHeadFile() {
        let head = URL(fileURLWithPath: "/tmp/research/authoring/HEAD.json")
        let observer = ResearchReportTreeFileObserver(localRef: head.absoluteString)

        XCTAssertEqual(observer.presentedItemURL, head.deletingLastPathComponent())
    }

    func testDirectoryWatchObservesAtomicHeadReplacement() async throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        let head = directory.appendingPathComponent("HEAD.json")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        try Data("{\"generation\":0}".utf8).write(to: head)
        addTeardownBlock { try? FileManager.default.removeItem(at: directory) }

        let observer = ResearchReportTreeFileObserver(localRef: head.absoluteString)
        observer.start()
        defer { observer.stop() }
        try Data("{\"generation\":1}".utf8).write(to: head, options: .atomic)

        let deadline = ContinuousClock.now + .seconds(2)
        while observer.revision == 0 && ContinuousClock.now < deadline {
            try await Task.sleep(for: .milliseconds(25))
        }
        XCTAssertGreaterThan(observer.revision, 0)
    }

    func testDirectoryWatchIgnoresUnchangedHeadGeneration() async throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        let head = directory.appendingPathComponent("HEAD.json")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        try Data("{\"generation\":7}".utf8).write(to: head)
        addTeardownBlock { try? FileManager.default.removeItem(at: directory) }

        let observer = ResearchReportTreeFileObserver(localRef: head.absoluteString)
        observer.start()
        defer { observer.stop() }
        try Data("unrelated".utf8).write(
            to: directory.appendingPathComponent("other.txt"), options: .atomic
        )
        try await Task.sleep(for: .milliseconds(350))

        XCTAssertEqual(observer.revision, 0)
    }

    func testStopCancelsPendingDirectoryNotification() async throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        let head = directory.appendingPathComponent("HEAD.json")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        try Data("{\"generation\":1}".utf8).write(to: head)
        addTeardownBlock { try? FileManager.default.removeItem(at: directory) }

        let observer = ResearchReportTreeFileObserver(localRef: head.absoluteString)
        observer.start()
        try Data("{\"generation\":2}".utf8).write(to: head, options: .atomic)
        observer.stop()
        try await Task.sleep(for: .milliseconds(350))

        XCTAssertEqual(observer.revision, 0)
    }
}
