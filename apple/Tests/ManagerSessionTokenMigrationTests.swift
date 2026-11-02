import CryptoKit
import Foundation
import Security
import XCTest
@testable import TradeResearch

final class ManagerSessionTokenMigrationTests: XCTestCase {
    private let current = "com.gtht.traderesearch.manager"
    private let old = "com.gtht.factortester.manager"

    func testLegacyTokenIsReadWithoutMutationAndMigratesOnSuccessfulSave() throws {
        let endpoint = try XCTUnwrap(URL(string: "https://\(UUID().uuidString.lowercased()).invalid"))
        let account = SHA256.hash(data: Data(endpoint.absoluteString.utf8)).map { String(format: "%02x", $0) }.joined()
        defer { ManagerSessionTokenStore.remove(for: endpoint) }
        XCTAssertEqual(put("legacy-test", service: old, account: account), errSecSuccess)
        XCTAssertEqual(ManagerSessionTokenStore.read(for: endpoint), "legacy-test")
        XCTAssertEqual(status(service: old, account: account), errSecSuccess)
        XCTAssertEqual(status(service: current, account: account), errSecItemNotFound)
        ManagerSessionTokenStore.save("replacement-test", for: endpoint)
        XCTAssertEqual(ManagerSessionTokenStore.read(for: endpoint), "replacement-test")
        XCTAssertEqual(status(service: old, account: account), errSecItemNotFound)
        XCTAssertEqual(status(service: current, account: account), errSecSuccess)
    }

    func testCurrentCredentialWinsAndLogoutRemovesBothNames() throws {
        let endpoint = try XCTUnwrap(URL(string: "https://\(UUID().uuidString.lowercased()).invalid"))
        let account = SHA256.hash(data: Data(endpoint.absoluteString.utf8)).map { String(format: "%02x", $0) }.joined()
        defer { ManagerSessionTokenStore.remove(for: endpoint) }
        XCTAssertEqual(put("old-test", service: old, account: account), errSecSuccess)
        XCTAssertEqual(put("current-test", service: current, account: account), errSecSuccess)
        XCTAssertEqual(ManagerSessionTokenStore.read(for: endpoint), "current-test")
        ManagerSessionTokenStore.remove(for: endpoint)
        XCTAssertEqual(status(service: old, account: account), errSecItemNotFound)
        XCTAssertEqual(status(service: current, account: account), errSecItemNotFound)
    }

    private func query(service: String, account: String) -> [String: Any] {
        [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service,
         kSecAttrAccount as String: account]
    }

    private func put(_ value: String, service: String, account: String) -> OSStatus {
        var item = query(service: service, account: account)
        item[kSecValueData as String] = Data(value.utf8)
        item[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        return SecItemAdd(item as CFDictionary, nil)
    }

    private func status(service: String, account: String) -> OSStatus {
        SecItemCopyMatching(query(service: service, account: account) as CFDictionary, nil)
    }
}
