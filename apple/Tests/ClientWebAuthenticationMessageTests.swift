import XCTest
@testable import TradeResearch

final class ClientWebAuthenticationMessageTests: XCTestCase {
    func testAuthenticationMessagesRequireCurrentManagerMainFrame() throws {
        let endpoint = try XCTUnwrap(URL(string: "https://manager.example:7998"))
        let body: [String: String] = ["action": "logout"]
        func action(_ main: Bool, _ host: String, _ current: URL?) -> ClientWebAuthenticationMessage.Action? {
            ClientWebAuthenticationMessage.authorizedAction(from: body, isMainFrame: main, scheme: "https",
                                                            host: host, port: 7998, endpoint: endpoint, currentEndpoint: current)
        }
        XCTAssertEqual(action(true, "manager.example", endpoint), .logout)
        XCTAssertNil(action(false, "manager.example", endpoint))
        XCTAssertNil(action(true, "attacker.example", endpoint))
        XCTAssertNil(action(true, "manager.example", URL(string: "https://other.example:7998")))
    }

    func testAcceptsOnlyDeclaredNativeAuthenticationActions() {
        XCTAssertEqual(
            ClientWebAuthenticationMessage.action(from: ["action": "logout"]),
            .logout
        )
        XCTAssertEqual(
            ClientWebAuthenticationMessage.action(
                from: ["action": "session-updated"]
            ),
            .sessionUpdated
        )
        XCTAssertNil(
            ClientWebAuthenticationMessage.action(
                from: ["action": "login-with-password"]
            )
        )
        XCTAssertNil(ClientWebAuthenticationMessage.action(from: "open"))
    }
}
