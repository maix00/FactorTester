import XCTest
@testable import FTClient

final class ResearchReportSectionDisclosureTests: XCTestCase {
    func testObligationChangesUseSpecialCollapsedPresentation() {
        XCTAssertEqual(
            ResearchReportSectionSpecialKind.resolve(
                displayKind: "research",
                hasObligationChanges: true
            ),
            .obligationChange
        )
    }

    func testGraphContinuationIsSpecialWhenNoObligationChangeExists() {
        XCTAssertEqual(
            ResearchReportSectionSpecialKind.resolve(
                displayKind: "graph_continuation",
                hasObligationChanges: false
            ),
            .graphContinuation
        )
    }

    func testOrdinarySectionHasNoSpecialMarker() {
        XCTAssertNil(
            ResearchReportSectionSpecialKind.resolve(
                displayKind: "research",
                hasObligationChanges: false
            )
        )
    }
}
