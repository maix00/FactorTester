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

    func testPageTurnRequiresRealOverscrollAndRelease() {
        var gesture = ResearchReportPageTurnGesture()
        gesture.update(direction: 1, overscroll: 30)
        gesture.update(direction: 1, overscroll: 71)
        XCTAssertNil(gesture.finish(canTurn: true))

        gesture.update(direction: 1, overscroll: 73)
        XCTAssertEqual(gesture.finish(canTurn: true), 1)
    }

    func testPageTurnRejectsUnavailableBoundaryAndResetsDirection() {
        var gesture = ResearchReportPageTurnGesture()
        gesture.update(direction: 1, overscroll: 80)
        XCTAssertNil(gesture.finish(canTurn: false))
        gesture.update(direction: 1, overscroll: 80)
        gesture.update(direction: -1, overscroll: 20)
        XCTAssertNil(gesture.finish(canTurn: true))
    }

    func testAdjacentChapterUsesExpectedLandingEdge() {
        XCTAssertEqual(
            ResearchReportAdjacentChapterNavigation.destination(direction: -1),
            .documentBottom
        )
        XCTAssertEqual(
            ResearchReportAdjacentChapterNavigation.destination(direction: 1),
            .chapterTop
        )
    }

    func testEmptyChapterIsReportedOnlyWithoutBodyContentOrChildren() {
        let empty = payload(id: "empty").components[0]
        XCTAssertTrue(ResearchDocumentComponentPresentation.isEmptyChapter(
            empty,
            children: []
        ))
        XCTAssertFalse(ResearchDocumentComponentPresentation.isEmptyChapter(
            empty,
            children: [ResearchDocumentComponent(
                id: "section",
                kind: "section",
                displayKind: "",
                parentID: empty.id,
                title: "内容",
                body: "",
                content: .none
            )]
        ))
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
