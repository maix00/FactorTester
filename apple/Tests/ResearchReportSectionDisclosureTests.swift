import XCTest
@testable import FTClient

final class ResearchReportSectionDisclosureTests: XCTestCase {
    func testObligationChangesUseSpecialCollapsedPresentation() {
        XCTAssertEqual(
            ResearchReportSectionSpecialKind.resolve(
                displayKind: "obligation_changes",
                sectionRole: nil,
                hasObligationChanges: false
            ),
            .obligationChange
        )
    }

    func testGraphContinuationIsSpecialWhenNoObligationChangeExists() {
        XCTAssertEqual(
            ResearchReportSectionSpecialKind.resolve(
                displayKind: "graph_continuation",
                sectionRole: nil,
                hasObligationChanges: false
            ),
            .graphContinuation
        )
    }

    func testOrdinarySectionHasNoSpecialMarker() {
        XCTAssertNil(
            ResearchReportSectionSpecialKind.resolve(
                displayKind: "research",
                sectionRole: nil,
                hasObligationChanges: false
            )
        )
    }
}
