import XCTest
@testable import FTClient

final class ManagerEndpointPolicyTests: XCTestCase {
    func testPrivateEndpointsRequireActualIPAddresses() {
        for value in ["localhost", "127.0.0.1", "127.1.2.3", "10.2.3.4", "172.16.0.1", "192.168.1.1", "::1", "fc00::1", "fd12::1", "fe80::1", "febf::1"] {
            XCTAssertTrue(ManagerEndpointPolicy.isPrivateNetwork(value), value)
        }
        for value in ["fc.example.com", "fd.example.com", "fe80.example.com", "10.x.1.2.3", "172.32.0.1", "8.8.8.8", "fec0::1", "https://10.0.0.1"] {
            XCTAssertFalse(ManagerEndpointPolicy.isPrivateNetwork(value), value)
        }
    }
}
