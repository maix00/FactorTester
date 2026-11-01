import XCTest
@testable import TradeResearch

final class ManagerEndpointPolicyTests: XCTestCase {
    func testPrivateEndpointsRequireActualIPAddresses() {
        for value in ["localhost", "127.0.0.1", "127.1.2.3", "10.2.3.4", "172.16.0.1", "192.168.1.1", "::1", "fc00::1", "fd12::1", "fe80::1", "febf::1"] {
            XCTAssertTrue(ManagerEndpointPolicy.isPrivateNetwork(value), value)
        }
        for value in ["fc.example.com", "fd.example.com", "fe80.example.com", "10.x.1.2.3", "172.32.0.1", "8.8.8.8", "fec0::1", "https://10.0.0.1"] {
            XCTAssertFalse(ManagerEndpointPolicy.isPrivateNetwork(value), value)
        }
    }

    func testDeviceProofHandoffStaysOnManagerAndHasOneTicket() throws {
        let endpoint = try XCTUnwrap(URL(string: "https://manager.example:7998"))
        let valid = "/auth/oidc/start?next=%2Fapp&device_ticket=abc-123"
        let result = try XCTUnwrap(ManagerDeviceAuthenticationService.validatedHandoff(valid, endpoint: endpoint))
        XCTAssertEqual(result.host, "manager.example")
        XCTAssertEqual(result.port, 7998)
        for invalid in [
            "https://other.example/auth/oidc/start?device_ticket=abc",
            "//other.example/auth/oidc/start?device_ticket=abc",
            "/auth/oidc/callback?device_ticket=abc",
            "/auth/oidc/start?device_ticket=abc&device_ticket=other",
            "/auth/oidc/start?device_ticket=",
            "/auth/oidc/start?device_ticket=abc&extra=1",
            "/auth/oidc/start?device_ticket=abc#fragment",
        ] {
            XCTAssertNil(ManagerDeviceAuthenticationService.validatedHandoff(invalid, endpoint: endpoint), invalid)
        }
    }
}
