import XCTest
@testable import FTClient

final class ResearchReportChapterPagingTests: XCTestCase {
    private let outline = ["one", "two", "three", "four", "five"]

    func testInitialReportNavigationTargetsLatestChapterBottom() {
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
        XCTAssertNil(ResearchReportInitialNavigation.destination(
            wasLoaded: false,
            hasExplicitTarget: true,
            outlineIDs: outline
        ))
    }

    func testPendingNavigationOwnsReloadFocusAndRailSelection() {
        XCTAssertEqual(
            ResearchReportNavigationFocus.preferred(
                pendingID: "target",
                selectedID: "old",
                initialID: "latest"
            ),
            "target"
        )
        XCTAssertEqual(
            ResearchReportNodeRailMetrics.currentComponentID(
                selectedID: "old",
                pendingID: "target"
            ),
            "target"
        )
    }

    func testLoadedDocumentReplacesOneChapterWithAnother() {
        var document = ResearchReportLoadedDocument()
        _ = document.apply(payload(id: "one"), focusedAt: "one")
        let result = document.apply(payload(id: "two"), focusedAt: "two")

        XCTAssertTrue(result.chapterChanged)
        XCTAssertEqual(document.rootComponentIDs, ["two"])
        XCTAssertTrue(document.containsChapter("two"))
        XCTAssertFalse(document.containsChapter("one"))
    }

    func testRailMarkerInfluenceKeepsNeighborFalloff() {
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

    func testWheelPagingRequiresSustainedBoundaryScroll() {
        var threshold = ResearchReportPageTurnThreshold()

        XCTAssertNil(threshold.consume(
            deltaY: -30, precise: true, atBoundary: true
        ))
        XCTAssertNil(threshold.consume(
            deltaY: -30, precise: true, atBoundary: true
        ))
        XCTAssertEqual(threshold.consume(
            deltaY: -20, precise: true, atBoundary: true
        ), 1)
    }

    func testWheelPagingResetsAwayFromBoundaryOrOnDirectionChange() {
        var threshold = ResearchReportPageTurnThreshold()
        XCTAssertNil(threshold.consume(
            deltaY: -60, precise: true, atBoundary: true
        ))
        XCTAssertNil(threshold.consume(
            deltaY: -20, precise: true, atBoundary: false
        ))
        XCTAssertNil(threshold.consume(
            deltaY: -60, precise: true, atBoundary: true
        ))
        XCTAssertNil(threshold.consume(
            deltaY: 20, precise: true, atBoundary: true
        ))
        XCTAssertEqual(threshold.consume(
            deltaY: 60, precise: true, atBoundary: true
        ), -1)
    }

    private func payload(id: String) -> ResearchReportTreePayload {
        ResearchReportTreePayload(
            title: "报告",
            generation: 1,
            focusedComponentID: id,
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
            loadedComponentIDs: [id],
            components: [ResearchDocumentComponent(
                id: id,
                kind: "chapter",
                displayKind: "",
                parentID: nil,
                title: id,
                body: "",
                content: .none
            )],
            assets: [],
            bindings: []
        )
    }
}
