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
                displayKind: "",
                sectionRole: "upgrade_reentry",
                hasObligationChanges: false
            ),
            .graphContinuation
        )
    }

    func testCapabilityDetourUsesItsOwnSpecialPresentation() {
        XCTAssertEqual(
            ResearchReportSectionSpecialKind.resolve(
                displayKind: "capability_detour",
                sectionRole: nil,
                hasObligationChanges: false
            ),
            .capabilityDetour
        )
    }

    func testGrillResolutionUsesAnAuthoredSpecialPresentation() {
        XCTAssertEqual(
            ResearchReportSectionSpecialKind.resolve(
                displayKind: "grill_resolution",
                sectionRole: nil,
                hasObligationChanges: false
            ),
            .grillResolution
        )
    }

    func testExternalReviewUsesTheSameSpecialSectionInfrastructure() {
        XCTAssertEqual(
            ResearchReportSectionSpecialKind.resolve(
                displayKind: "external_review",
                sectionRole: nil,
                hasObligationChanges: false
            ),
            .externalReview
        )
    }

    func testTestResultUsesOneCollapsibleParentForArtifactsAndAnalysis() {
        XCTAssertEqual(
            ResearchReportSectionSpecialKind.resolve(
                displayKind: "test_result",
                sectionRole: nil,
                hasObligationChanges: false
            ),
            .testResult
        )
    }

    func testEntryRequirementsUseSystemSpecialPresentation() {
        XCTAssertEqual(
            ResearchReportSectionSpecialKind.resolve(
                displayKind: "entry_requirements",
                sectionRole: nil,
                hasObligationChanges: false
            ),
            .entryRequirements
        )
    }

    func testAnyRequiredObligationCategoryUsesAuthoredSpecialPresentation() {
        XCTAssertEqual(
            ResearchReportSectionSpecialKind.resolve(
                displayKind: "obligation_requirement",
                sectionRole: nil,
                hasObligationChanges: false
            ),
            .obligationRequirement
        )
    }

    func testObligationCoverageUsesSeparatePresentation() {
        XCTAssertEqual(
            ResearchReportSectionSpecialKind.resolve(
                displayKind: "obligation_coverage",
                sectionRole: nil,
                hasObligationChanges: false
            ),
            .obligationCoverage
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
