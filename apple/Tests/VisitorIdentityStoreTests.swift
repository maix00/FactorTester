import XCTest
@testable import TradeResearch

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

    func testLegacyIdentityIsMigratedWithoutChangingVisitor() {
        let suite = "visitor-identity-migration-\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }
        let old = UUID().uuidString
        defaults.set(old, forKey: VisitorIdentityStore.legacyDefaultsKey)
        XCTAssertEqual(VisitorIdentityStore.current(defaults: defaults), old.lowercased())
        XCTAssertEqual(defaults.string(forKey: VisitorIdentityStore.defaultsKey), old.lowercased())
        XCTAssertNil(defaults.string(forKey: VisitorIdentityStore.legacyDefaultsKey))
    }

    func testExistingCurrentIdentityWinsWithoutDiscardingConflictingLegacyIdentity() {
        let suite = "visitor-identity-conflict-\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }
        let current = UUID().uuidString.lowercased()
        let legacy = UUID().uuidString.lowercased()
        defaults.set(current, forKey: VisitorIdentityStore.defaultsKey)
        defaults.set(legacy, forKey: VisitorIdentityStore.legacyDefaultsKey)
        XCTAssertEqual(VisitorIdentityStore.current(defaults: defaults), current)
        XCTAssertEqual(defaults.string(forKey: VisitorIdentityStore.legacyDefaultsKey), legacy)
    }
}
