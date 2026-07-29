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

    func testNavigationWindowLoadsTwoChaptersAhead() {
        XCTAssertEqual(
            ResearchReportChapterWindow.loadedIDs(
                outlineIDs: outline,
                focusedID: "three",
                radius: 2
            ),
            outline
        )
    }

    func testOverlappingWindowsMergeWithoutDroppingVisibleChapters() {
        var document = ResearchReportLoadedDocument()
        _ = document.apply(
            payload(ids: ["one", "two", "three"], focus: "one"),
            focusedAt: "one"
        )

        let result = document.apply(
            payload(ids: ["two", "three", "four"], focus: "three"),
            focusedAt: "three"
        )

        XCTAssertFalse(result.replaced)
        XCTAssertEqual(Set(document.rootComponentIDs), [
            "one", "two", "three", "four",
        ])
        XCTAssertTrue(document.containsWindow(centeredAt: "three", radius: 1))
    }

    func testDisconnectedNavigationReplacesTheMountedWindow() {
        var document = ResearchReportLoadedDocument()
        _ = document.apply(
            payload(ids: ["one", "two"], focus: "one"),
            focusedAt: "one"
        )

        let result = document.apply(
            payload(ids: ["four", "five"], focus: "five"),
            focusedAt: "five"
        )

        XCTAssertTrue(result.replaced)
        XCTAssertEqual(document.rootComponentIDs, ["four", "five"])
    }

    func testPrependingAWindowRequestsAnchorPreservation() {
        var document = ResearchReportLoadedDocument()
        _ = document.apply(
            payload(ids: ["three", "four", "five"], focus: "five"),
            focusedAt: "five"
        )

        let result = document.apply(
            payload(ids: ["one", "two", "three"], focus: "three"),
            focusedAt: "three"
        )

        XCTAssertTrue(result.addedBeforeFocus)
    }

    func testChatGPTRailMarkerInfluenceMatchesNeighborFalloff() {
        XCTAssertEqual(
            ResearchReportNodeRailMetrics.markerScale(
                index: 4,
                targetIndex: nil
            ),
            0.2308,
            accuracy: 0.0001
        )
        XCTAssertEqual(
            ResearchReportNodeRailMetrics.markerScale(
                index: 4,
                targetIndex: 4
            ),
            1,
            accuracy: 0.0001
        )
        XCTAssertGreaterThan(
            ResearchReportNodeRailMetrics.markerScale(
                index: 3,
                targetIndex: 4
            ),
            ResearchReportNodeRailMetrics.markerScale(
                index: 2,
                targetIndex: 4
            )
        )
    }

    private func payload(
        ids: [String],
        focus: String
    ) -> ResearchReportTreePayload {
        ResearchReportTreePayload(
            title: "报告",
            generation: 1,
            focusedComponentID: focus,
            outline: outline.map {
                ResearchReportOutlineItem(
                    componentID: $0,
                    title: $0,
                    fallbackTitle: $0,
                    createdAt: 0,
                    references: []
                )
            },
            outlineIDs: outline,
            loadedComponentIDs: ids,
            components: ids.map {
                ResearchDocumentComponent(
                    id: $0,
                    kind: "chapter",
                    displayKind: "",
                    parentID: nil,
                    title: $0,
                    body: "",
                    content: .none
                )
            },
            assets: [],
            bindings: []
        )
    }
}
