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

    func testNavigationWindowKeepsFiveChaptersOnEachSide() {
        let values = (0..<15).map(String.init)
        XCTAssertEqual(
            ResearchReportChapterWindow.loadedIDs(
                outlineIDs: values,
                focusedID: "7",
                radius: ResearchReportChapterWindow.navigationRadius
            ),
            Array(values[2...12])
        )
    }

    func testPendingNavigationOwnsReloadFocusAndRailSelection() {
        XCTAssertEqual(
            ResearchReportNavigationFocus.preferred(
                pendingID: "far-target",
                selectedID: "old-node",
                initialID: "latest"
            ),
            "far-target"
        )
        XCTAssertEqual(
            ResearchReportNodeRailMetrics.currentComponentID(
                selectedID: "old-node",
                pendingID: "far-target"
            ),
            "far-target"
        )
    }

    func testSelectedNavigationOwnsFocusWithoutPendingTarget() {
        XCTAssertEqual(
            ResearchReportNavigationFocus.preferred(
                pendingID: "",
                selectedID: "visible-node",
                initialID: "latest"
            ),
            "visible-node"
        )
        XCTAssertEqual(
            ResearchReportNodeRailMetrics.currentComponentID(
                selectedID: "visible-node",
                pendingID: ""
            ),
            "visible-node"
        )
    }

    func testOverlappingWindowsReplaceTheMountedDataWindow() {
        var document = ResearchReportLoadedDocument()
        _ = document.apply(
            payload(ids: ["one", "two", "three"], focus: "one"),
            focusedAt: "one"
        )

        let result = document.apply(
            payload(ids: ["two", "three", "four"], focus: "three"),
            focusedAt: "three"
        )

        XCTAssertTrue(result.windowChanged)
        XCTAssertEqual(Set(document.rootComponentIDs), [
            "two", "three", "four",
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

        XCTAssertTrue(result.windowChanged)
        XCTAssertEqual(document.rootComponentIDs, ["four", "five"])
    }

    func testPrependingAWindowDoesNotRetainTheOldTail() {
        var document = ResearchReportLoadedDocument()
        _ = document.apply(
            payload(ids: ["three", "four", "five"], focus: "five"),
            focusedAt: "five"
        )

        let result = document.apply(
            payload(ids: ["one", "two", "three"], focus: "three"),
            focusedAt: "three"
        )

        XCTAssertTrue(result.windowChanged)
        XCTAssertEqual(document.rootComponentIDs, ["one", "two", "three"])
    }

    func testSequentialNavigationKeepsOnlyTheLatestBoundedWindow() {
        var document = ResearchReportLoadedDocument()
        for focus in outline {
            let ids = ResearchReportChapterWindow.loadedIDs(
                outlineIDs: outline,
                focusedID: focus,
                radius: 2
            )
            _ = document.apply(
                payload(ids: ids, focus: focus),
                focusedAt: focus
            )
            XCTAssertLessThanOrEqual(document.rootComponentIDs.count, 5)
            XCTAssertEqual(document.rootComponentIDs, ids)
        }
    }

    func testLoadedChapterWithoutItsNeighborsRequiresAnotherWindowLoad() {
        var document = ResearchReportLoadedDocument()
        _ = document.apply(
            payload(ids: ["three"], focus: "three"),
            focusedAt: "three"
        )

        XCTAssertTrue(document.containsChapter("three"))
        XCTAssertFalse(document.containsWindow(
            centeredAt: "three",
            radius: 2
        ))
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

    func testLongChapterRemainsActiveUntilNextChapterCrossesAnchor() {
        XCTAssertEqual(
            ResearchReportChapterViewport.activeID(
                positions: ["one": -700, "two": 420],
                orderedIDs: ["one", "two"]
            ),
            "one"
        )
        XCTAssertEqual(
            ResearchReportChapterViewport.activeID(
                positions: ["one": -1_100, "two": 90],
                orderedIDs: ["one", "two"]
            ),
            "two"
        )
    }

    func testFirstMaterializedChapterIsActiveBeforeAnyEdgeCrossesAnchor() {
        XCTAssertEqual(
            ResearchReportChapterViewport.activeID(
                positions: ["three": 180, "four": 520],
                orderedIDs: ["one", "two", "three", "four"]
            ),
            "three"
        )
    }

    func testScrollCompletesOnlyAfterLoadedTargetCrossesReadingAnchor() {
        XCTAssertFalse(
            ResearchReportChapterViewport.completedScroll(
                to: "three",
                positions: ["one": -900, "two": 80, "three": 420],
                loadedIDs: ["two", "three"]
            )
        )
        XCTAssertTrue(
            ResearchReportChapterViewport.completedScroll(
                to: "three",
                positions: ["one": -1_100, "two": -440, "three": 72],
                loadedIDs: ["two", "three"]
            )
        )
    }

    func testPlaceholderCannotAcknowledgeProgrammaticScroll() {
        XCTAssertFalse(
            ResearchReportChapterViewport.completedScroll(
                to: "three",
                positions: ["three": 72],
                loadedIDs: ["one", "two"]
            )
        )
    }

    func testShortTrailingChapterCompletesWhenVisibleAtDocumentBottom() {
        XCTAssertTrue(
            ResearchReportChapterViewport.completedScroll(
                to: "three",
                positions: ["two": -240, "three": 280],
                loadedIDs: ["two", "three"],
                isTrailingTarget: true,
                viewportHeight: 620
            )
        )
        XCTAssertFalse(
            ResearchReportChapterViewport.completedScroll(
                to: "three",
                positions: ["two": -240, "three": 720],
                loadedIDs: ["two", "three"],
                isTrailingTarget: true,
                viewportHeight: 620
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
