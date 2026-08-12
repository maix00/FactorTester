import Foundation
import XCTest
@testable import FTClient

final class ManagerNetworkInfoTests: XCTestCase {
    func testDiscoveredPublicTargetTakesPriorityOverPeerCallback() throws {
        let info = try decode(
            advertised: "http://127.0.0.1:17998",
            publicServer: false,
            target: #"{"server_id":"remote-main","role":"main","endpoint":"https://101.133.144.27:7998","latency_ms":8,"load":0}"#
        )

        XCTAssertEqual(
            info.publicEndpointSummary,
            "https://101.133.144.27:7998 (remote-main)"
        )
    }

    func testPeerCallbackRemainsTheFallbackWithoutAPublicTarget() throws {
        let info = try decode(
            advertised: "https://manager.example:7998",
            publicServer: true,
            target: "null"
        )

        XCTAssertEqual(
            info.publicEndpointSummary,
            "https://manager.example:7998 (local-feat)"
        )
    }

    func testPrivatePeerCallbackIsNotPresentedAsAPublicServer() throws {
        let info = try decode(
            advertised: "http://127.0.0.1:17998",
            publicServer: false,
            target: "null"
        )

        XCTAssertTrue(info.publicEndpointSummary.isEmpty)
    }

    private func decode(
        advertised: String,
        publicServer: Bool,
        target: String
    ) throws -> ManagerNetworkInfo {
        let json = """
        {
          "server_id": "local-feat",
          "role": "feat",
          "internal_addresses": ["192.168.1.10"],
          "manager_port": 7998,
          "public_server": \(publicServer),
          "advertised_public_endpoint": "\(advertised)",
          "current_public_target": \(target)
        }
        """
        return try JSONDecoder().decode(
            ManagerNetworkInfo.self,
            from: Data(json.utf8)
        )
    }
}
