import XCTest
@testable import FTClient

@MainActor
final class PersonalWorkspaceAuthorizationCoordinatorTests: XCTestCase {
    func testExistingAuthorizationDoesNotPresentPanel() {
        var promptCount = 0
        let coordinator = PersonalWorkspaceAuthorizationCoordinator(
            hasAuthorization: { _ in true },
            requestAuthorization: { _ in promptCount += 1; return true }
        )

        coordinator.requestIfNeeded(principal: "18717974771")

        XCTAssertEqual(promptCount, 0)
    }

    func testMissingAuthorizationPresentsOncePerPrincipal() {
        var promptCount = 0
        let coordinator = PersonalWorkspaceAuthorizationCoordinator(
            hasAuthorization: { _ in false },
            requestAuthorization: { _ in promptCount += 1; return true }
        )

        coordinator.requestIfNeeded(principal: "18717974771")
        coordinator.requestIfNeeded(principal: "18717974771")

        XCTAssertEqual(promptCount, 1)
    }

    func testInvalidPrincipalNeverPresentsPanel() {
        var promptCount = 0
        let coordinator = PersonalWorkspaceAuthorizationCoordinator(
            hasAuthorization: { _ in false },
            requestAuthorization: { _ in promptCount += 1; return true }
        )

        coordinator.requestIfNeeded(principal: "../another-user")

        XCTAssertEqual(promptCount, 0)
    }
}
