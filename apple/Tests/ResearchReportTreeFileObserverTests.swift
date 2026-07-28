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
}
