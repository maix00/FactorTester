import XCTest
@testable import TradeResearch

final class RetiredPasswordCredentialsTests: XCTestCase {
    func testCleanupTargetsOnlyTheRetiredPasswordEntries() {
        var removed: [String] = []
        RetiredPasswordCredentials.remove { account, service in removed.append(service + "/" + account) }
        XCTAssertEqual(removed, ["com.gtht.client.session/default", "com.gtht.client.session.user-presence/default"])
        // Device keys, Manager session tokens and adapter credentials remain
        // outside this deliberately narrow cleanup operation.
        XCTAssertFalse(removed.contains { $0.contains("manager") || $0.contains("device") || $0.contains("adapters") })
    }
}
