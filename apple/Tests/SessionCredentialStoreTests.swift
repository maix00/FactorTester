import Foundation
import XCTest
@testable import FTClient

final class SessionCredentialStoreTests: XCTestCase {
    func testLegacyServerBoundCredentialRemainsDecodable() throws {
        let data = try XCTUnwrap(
            """
            {"username":"alice","password":"secret","serverURL":"http://127.0.0.1:8141"}
            """.data(using: .utf8)
        )

        let credentials = try JSONDecoder().decode(
            SavedSessionCredentials.self,
            from: data
        )

        XCTAssertEqual(credentials.username, "alice")
        XCTAssertEqual(credentials.serverURL, "http://127.0.0.1:8141")
    }
}
