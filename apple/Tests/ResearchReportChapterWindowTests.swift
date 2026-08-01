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

    func testOverlappingWindowsKeepOnlyTheAuthoritativeMountedWindow() {
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
        XCTAssertEqual(document.rootComponentIDs, ["two", "three", "four"])
        XCTAssertFalse(result.prependedChapters)
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
        XCTAssertFalse(result.prependedChapters)
    }

    func testPrependingAWindowReplacesTheOldTailWithinTheBoundedWindow() {
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
        XCTAssertTrue(result.prependedChapters)
        XCTAssertEqual(document.rootComponentIDs, ["one", "two", "three"])
    }

    func testSequentialOverlappingNavigationNeverExceedsItsWindow() {
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
            XCTAssertLessThanOrEqual(document.rootComponentIDs.count, ids.count)
            XCTAssertEqual(document.rootComponentIDs, ids)
        }
        XCTAssertEqual(document.rootComponentIDs, ["three", "four", "five"])
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

    func testPassiveReadingUsesAStableTwoChapterBuffer() {
        var document = ResearchReportLoadedDocument()
        _ = document.apply(
            payload(ids: ["one", "two", "three", "four", "five"], focus: "three"),
            focusedAt: "three"
        )

        XCTAssertTrue(document.containsNavigationBuffer(around: "three"))
        XCTAssertTrue(document.containsNavigationBuffer(around: "two"))
    }

    func testLayoutAnchorKeepsItsViewportPositionAcrossWindowReplacement() {
        XCTAssertEqual(
            ResearchReportScrollAnchorMath.restoredViewportOffset(
                currentOffset: 640,
                previousAnchorPosition: 80,
                currentAnchorPosition: -220
            ),
            340
        )
    }

    func testInitialReportNavigationTargetsTheDocumentBottom() {
        XCTAssertEqual(
            ResearchReportInitialNavigation.destination(
                wasLoaded: false,
                hasExplicitTarget: false,
                outlineIDs: outline
            ),
            ResearchReportInitialDestination(
                componentID: "five",
                scrollDestination: .documentBottom
            )
        )
    }

    func testExplicitNavigationWinsOverInitialBottomPosition() {
        XCTAssertNil(
            ResearchReportInitialNavigation.destination(
                wasLoaded: false,
                hasExplicitTarget: true,
                outlineIDs: outline
            )
        )
    }

    func testReadingAnchorKeepsChapterRelativeOffset() {
        XCTAssertEqual(
            ResearchReportChapterViewport.readingAnchor(
                positions: ["one": -480, "two": 360],
                orderedIDs: ["one", "two"]
            ),
            ResearchReportReadingAnchor(
                componentID: "one",
                chapterOffset: 480
            )
        )
        XCTAssertEqual(
            ResearchReportScrollAnchorMath.restoredReadingOffset(
                currentOffset: 1_000,
                chapterOffset: 480
            ),
            1_480
        )
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
                canClampAtDocumentBottom: true,
                viewportHeight: 620
            )
        )
        XCTAssertFalse(
            ResearchReportChapterViewport.completedScroll(
                to: "three",
                positions: ["two": -240, "three": 720],
                loadedIDs: ["two", "three"],
                canClampAtDocumentBottom: true,
                viewportHeight: 620
            )
        )
    }

    func testVisibleNearTailChapterCompletesWhenTailWindowIsLoaded() {
        XCTAssertTrue(
            ResearchReportChapterViewport.completedScroll(
                to: "two",
                positions: ["two": 240, "three": 510],
                loadedIDs: ["two", "three"],
                canClampAtDocumentBottom: true,
                viewportHeight: 620
            )
        )
    }

    func testOffscreenNearTailChapterDoesNotCompleteFromBottomClamp() {
        XCTAssertFalse(
            ResearchReportChapterViewport.completedScroll(
                to: "two",
                positions: ["two": -200, "three": 90],
                loadedIDs: ["two", "three"],
                canClampAtDocumentBottom: true,
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
