import XCTest
@testable import FTClient

final class ClientWebAuthenticationMessageTests: XCTestCase {
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
