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

    func testSwitchProbeDoesNotForwardHostCookiesAcrossPorts() throws {
        let target = try XCTUnwrap(ManagerConnectionBridgeContract.endpoint("http://127.0.0.1:8998"))
        let empty = try XCTUnwrap(ManagerConnectionBridgeContract.probeRequest(target: target, token: ""))
        XCTAssertEqual(empty.url?.absoluteString, "http://127.0.0.1:8998/api/session")
        XCTAssertNil(empty.value(forHTTPHeaderField: "Cookie"))
        XCTAssertNil(empty.value(forHTTPHeaderField: "Authorization"))
        let saved = try XCTUnwrap(ManagerConnectionBridgeContract.probeRequest(target: target, token: "target-token"))
        XCTAssertEqual(saved.value(forHTTPHeaderField: "Authorization"), "Bearer target-token")
        XCTAssertNil(saved.value(forHTTPHeaderField: "Cookie"))
        let config = ManagerConnectionBridgeContract.probeSessionConfiguration()
        XCTAssertNil(config.httpCookieStorage)
        XCTAssertFalse(config.httpShouldSetCookies)
    }
}
