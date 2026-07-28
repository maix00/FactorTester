import XCTest
@testable import FTClient

final class ResearchReportChapterWindowTests: XCTestCase {
    private let outline = ["one", "two", "three", "four", "five"]

    func testLoadsFocusedChapterAndImmediateNeighbors() {
        XCTAssertEqual(
            ResearchReportChapterWindow.loadedIDs(
                outlineIDs: outline, focusedID: "three"
            ),
            ["two", "three", "four"]
        )
    }

    func testDefaultsToLatestChapter() {
        XCTAssertEqual(
            ResearchReportChapterWindow.loadedIDs(
                outlineIDs: outline, focusedID: nil
            ),
            ["four", "five"]
        )
    }

    func testPrefetchesOnlyAdjacentUnloadedChapters() {
        XCTAssertEqual(
            ResearchReportChapterWindow.prefetchIDs(
                outlineIDs: outline, loadedIDs: ["two", "three", "four"]
            ),
            ["one", "five"]
        )
    }
}
