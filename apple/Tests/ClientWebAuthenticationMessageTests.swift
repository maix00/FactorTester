import XCTest
@testable import FTClient

final class ClientWebAuthenticationMessageTests: XCTestCase {
    func testAcceptsOnlyDeclaredNativeAuthenticationActions() {
        XCTAssertEqual(
            ClientWebAuthenticationMessage.action(from: ["action": "open"]),
            .open
        )
        XCTAssertEqual(
            ClientWebAuthenticationMessage.action(from: ["action": "logout"]),
            .logout
        )
        XCTAssertNil(
            ClientWebAuthenticationMessage.action(
                from: ["action": "login-with-password"]
            )
        )
        XCTAssertNil(ClientWebAuthenticationMessage.action(from: "open"))
    }
}
