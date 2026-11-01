import Foundation
import XCTest
@testable import TradeResearch

final class ManagerConnectionBridgeContractTests: XCTestCase {
    func testEndpointValidationRestrictsUntrustedLocations() {
        XCTAssertNotNil(ManagerConnectionBridgeContract.endpoint("http://127.0.0.1:7998"))
        XCTAssertNotNil(ManagerConnectionBridgeContract.endpoint("https://example.com"))
        for value in ["http://fc.example.com", "http://8.8.8.8", "https://u:p@example.com",
                      "https://example.com/path", "https://example.com/?q=x", "https://example.com/#x",
                      " https://example.com", "ftp://example.com"] {
            XCTAssertNil(ManagerConnectionBridgeContract.endpoint(value), value)
        }
    }
}
