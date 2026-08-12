import XCTest
@testable import FTClient

final class ResearchHumanGateOverrideServiceTests: XCTestCase {
    func testEndpointUsesTheExactBranchScopedNativeRoute() throws {
        let endpoint = ResearchHumanGateOverrideService.endpoint(
            baseURL: try XCTUnwrap(URL(string: "http://127.0.0.1:8141")),
            instanceID: "instance-a",
            branchID: "branch-b"
        )

        XCTAssertEqual(
            endpoint.absoluteString,
            "http://127.0.0.1:8141/api/research-graph-instances/instance-a/branches/branch-b/human-gate-override"
        )
    }
}
