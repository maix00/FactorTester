import XCTest
@testable import FTClient

final class VisitorIdentityStoreTests: XCTestCase {
    func testIdentityIsStableAndCanonicalPerInstallation() {
        let suite = "visitor-identity-\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }

        let first = VisitorIdentityStore.current(defaults: defaults)
        let second = VisitorIdentityStore.current(defaults: defaults)

        XCTAssertEqual(first, second)
        XCTAssertTrue(VisitorIdentityStore.isValid(first))
        XCTAssertEqual(first, first.lowercased())
    }

    func testInvalidStoredValueIsReplaced() {
        let suite = "visitor-identity-invalid-\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }
        defaults.set("account-name", forKey: VisitorIdentityStore.defaultsKey)

        let value = VisitorIdentityStore.current(defaults: defaults)

        XCTAssertTrue(VisitorIdentityStore.isValid(value))
        XCTAssertNotEqual(value, "account-name")
    }
}
