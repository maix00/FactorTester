import Foundation
import XCTest
@testable import TradeResearch

final class LocalResearchBridgeContractTests: XCTestCase {
    func testOnlyCurrentManagerOriginIsAllowed() throws {
        let manager = try XCTUnwrap(URL(string: "https://manager.example:7998"))
        XCTAssertTrue(LocalResearchBridgeContract.sameOrigin(scheme: "https", host: "MANAGER.example", port: 7998, endpoint: manager))
        XCTAssertFalse(LocalResearchBridgeContract.sameOrigin(scheme: "http", host: "manager.example", port: 7998, endpoint: manager))
        XCTAssertFalse(LocalResearchBridgeContract.sameOrigin(scheme: "https", host: "other.example", port: 7998, endpoint: manager))
        XCTAssertFalse(LocalResearchBridgeContract.sameOrigin(scheme: "https", host: "manager.example", port: 443, endpoint: manager))
        let defaultPort = try XCTUnwrap(URL(string: "https://manager.example"))
        XCTAssertTrue(LocalResearchBridgeContract.sameOrigin(scheme: "https", host: "manager.example", port: 0, endpoint: defaultPort))
    }
}
