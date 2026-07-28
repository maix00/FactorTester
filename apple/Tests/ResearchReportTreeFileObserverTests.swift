import XCTest
@testable import FTClient

final class ResearchReportTreeFileObserverTests: XCTestCase {
    func testObservesAuthoringDirectoryRatherThanHeadFile() {
        let head = URL(fileURLWithPath: "/tmp/research/authoring/HEAD.json")
        let observer = ResearchReportTreeFileObserver(localRef: head.absoluteString)

        XCTAssertEqual(observer.presentedItemURL, head.deletingLastPathComponent())
    }
}
