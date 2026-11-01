import Foundation
import XCTest
@testable import TradeResearch

final class SessionCredentialStoreTests: XCTestCase {
    func testCredentialsAreNeverReplayedToAnotherManager() throws {
        let saved = SavedSessionCredentials(username: "alice", password: "secret", serverURL: "https://Manager.EXAMPLE")
        XCTAssertTrue(SessionCredentialStore.matchesManager(saved, endpoint: URL(string: "https://manager.example:443/")))
        XCTAssertFalse(SessionCredentialStore.matchesManager(saved, endpoint: URL(string: "https://manager.example:7998")))
        XCTAssertFalse(SessionCredentialStore.matchesManager(saved, endpoint: URL(string: "http://manager.example")))
        XCTAssertFalse(SessionCredentialStore.matchesManager(saved, endpoint: URL(string: "https://other.example")))
        let legacy = SavedSessionCredentials(username: "alice", password: "secret", serverURL: nil)
        XCTAssertFalse(SessionCredentialStore.matchesManager(legacy, endpoint: URL(string: "https://manager.example")))
    }

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
