import Foundation
import Security
import XCTest
@testable import TradeResearch

final class ManagerDeviceKeyMigrationTests: XCTestCase {
    func testDeviceSignaturePadsShortCanonicalIntegers() throws {
        // DER INTEGERs may be shorter than the 32-byte P-256 output width.
        let der = Data([0x30, 0x06, 0x02, 0x01, 0x01, 0x02, 0x01, 0x7f])
        let signature = try ManagerDeviceKeyStore.p1363Signature(fromDER: der)
        XCTAssertEqual(signature, Data(repeating: 0, count: 31) + Data([1])
                       + Data(repeating: 0, count: 31) + Data([0x7f]))
    }

    func testDeviceSignatureAcceptsRequiredSignPaddingAndRejectsMalformedDER() throws {
        let padded = Data([0x30, 0x07, 0x02, 0x02, 0x00, 0x80, 0x02, 0x01, 0x01])
        let signature = try ManagerDeviceKeyStore.p1363Signature(fromDER: padded)
        XCTAssertEqual(signature, Data(repeating: 0, count: 31) + Data([0x80])
                       + Data(repeating: 0, count: 31) + Data([1]))
        let malformed: [[UInt8]] = [
            [0x30, 0x06, 0x02, 0x01, 0x80, 0x02, 0x01, 0x01], // negative integer
            [0x30, 0x07, 0x02, 0x02, 0x00, 0x01, 0x02, 0x01, 0x01], // redundant zero
            [0x30, 0x06, 0x02, 0x01, 0x01, 0x02, 0x01, 0x01, 0x00], // trailing byte
        ]
        for der in malformed {
            XCTAssertThrowsError(try ManagerDeviceKeyStore.p1363Signature(fromDER: Data(der)))
        }
    }

    func testDeviceKeyRetagKeepsPublicIdentityAndSigning() throws {
        try exercise(secureEnclave: false)
    }

    func testSecureEnclaveRetagKeepsPublicIdentityAndSigningWhenAvailable() throws {
        do { try exercise(secureEnclave: true) }
        catch KeyFixtureError.unavailable { throw XCTSkip("Secure Enclave is unavailable to this test host") }
    }

    func testConflictingCurrentKeyNeverReplacesLegacyIdentity() throws {
        let id = UUID().uuidString
        let old = Data(("tr-test-old-" + id).utf8), current = Data(("tr-test-new-" + id).utf8)
        defer { remove(old); remove(current) }
        let first = try makeKey(old, secureEnclave: false)
        let second = try makeKey(current, secureEnclave: false)
        let expected = try ManagerDeviceKeyStore.publicJWK(for: XCTUnwrap(SecKeyCopyPublicKey(first)))
        XCTAssertNil(ManagerDeviceKeyStore.migrateKey(currentTag: current, legacyTag: old, publicKey: expected))
        XCTAssertEqual(publicData(lookup(old)), publicData(first))
        XCTAssertEqual(publicData(lookup(current)), publicData(second))
    }

    func testMetadataRetagUsesIsolatedKeychainEntries() throws {
        let id = UUID().uuidString
        let old = "tr-test-old-" + id, current = "tr-test-new-" + id, account = "fixture"
        let value = Data("synthetic-device-metadata".utf8)
        let oldQuery: [CFString: Any] = [kSecClass: kSecClassGenericPassword, kSecAttrService: old, kSecAttrAccount: account]
        let newQuery: [CFString: Any] = [kSecClass: kSecClassGenericPassword, kSecAttrService: current, kSecAttrAccount: account]
        defer { SecItemDelete(oldQuery as CFDictionary); SecItemDelete(newQuery as CFDictionary) }
        var item = oldQuery; item[kSecValueData] = value
        XCTAssertEqual(SecItemAdd(item as CFDictionary, nil), errSecSuccess)
        XCTAssertEqual(ManagerDeviceKeyStore.readMetadata(service: current, legacy: old, account: account), value)
        XCTAssertEqual(SecItemCopyMatching(newQuery as CFDictionary, nil), errSecSuccess)
        XCTAssertEqual(SecItemCopyMatching(oldQuery as CFDictionary, nil), errSecItemNotFound)
    }

    func testConflictingMetadataIsPreservedAndRejected() throws {
        let id = UUID().uuidString
        let old = "tr-test-old-" + id, current = "tr-test-new-" + id, account = "fixture"
        func item(_ service: String) -> [CFString: Any] {
            [kSecClass: kSecClassGenericPassword, kSecAttrService: service, kSecAttrAccount: account]
        }
        defer { SecItemDelete(item(old) as CFDictionary); SecItemDelete(item(current) as CFDictionary) }
        for (name, device) in [(old, "device-a"), (current, "device-b")] {
            var value = item(name)
            value[kSecValueData] = try JSONEncoder().encode(ManagerDeviceCredential(
                deviceID: device, username: "fixture", publicKey: ["x": device], secureEnclave: false))
            XCTAssertEqual(SecItemAdd(value as CFDictionary, nil), errSecSuccess)
        }
        XCTAssertNil(ManagerDeviceKeyStore.readMetadata(service: current, legacy: old, account: account))
        XCTAssertEqual(SecItemCopyMatching(item(old) as CFDictionary, nil), errSecSuccess)
        XCTAssertEqual(SecItemCopyMatching(item(current) as CFDictionary, nil), errSecSuccess)
    }

    private func exercise(secureEnclave: Bool) throws {
        let id = UUID().uuidString
        let old = Data(("tr-test-old-" + id).utf8), current = Data(("tr-test-new-" + id).utf8)
        defer { remove(old); remove(current) }
        let original = try makeKey(old, secureEnclave: secureEnclave)
        let publicKey = try XCTUnwrap(SecKeyCopyPublicKey(original))
        let expected = try ManagerDeviceKeyStore.publicJWK(for: publicKey)
        let resolved = try XCTUnwrap(ManagerDeviceKeyStore.migrateKey(currentTag: current, legacyTag: old, publicKey: expected))
        XCTAssertEqual(publicData(resolved), publicData(original))
        let message = Data("synthetic challenge".utf8)
        var error: Unmanaged<CFError>?
        let signature = try XCTUnwrap(SecKeyCreateSignature(resolved, .ecdsaSignatureMessageX962SHA256, message as CFData, &error))
        XCTAssertTrue(SecKeyVerifySignature(publicKey, .ecdsaSignatureMessageX962SHA256, message as CFData, signature, &error))
        if lookup(current) != nil {
            XCTAssertNil(lookup(old))
        } else {
            XCTAssertNotNil(lookup(old), "An unsupported retag must preserve the original key")
        }
    }

    private enum KeyFixtureError: Error { case unavailable }
    private func makeKey(_ tag: Data, secureEnclave: Bool) throws -> SecKey {
        var attributes: [CFString: Any] = [kSecAttrKeyType: kSecAttrKeyTypeECSECPrimeRandom,
            kSecAttrKeySizeInBits: 256, kSecAttrIsPermanent: true, kSecAttrApplicationTag: tag]
        if secureEnclave {
            var error: Unmanaged<CFError>?
            guard let access = SecAccessControlCreateWithFlags(nil, kSecAttrAccessibleWhenUnlockedThisDeviceOnly,
                                                               .privateKeyUsage, &error) else { throw KeyFixtureError.unavailable }
            attributes[kSecAttrAccessControl] = access
            attributes[kSecAttrTokenID] = kSecAttrTokenIDSecureEnclave
        }
        var error: Unmanaged<CFError>?
        guard let key = SecKeyCreateRandomKey(attributes as CFDictionary, &error) else { throw KeyFixtureError.unavailable }
        return key
    }
    private func lookup(_ tag: Data) -> SecKey? {
        var value: CFTypeRef?
        let query: [CFString: Any] = [kSecClass: kSecClassKey, kSecAttrKeyClass: kSecAttrKeyClassPrivate, kSecAttrKeyType: kSecAttrKeyTypeECSECPrimeRandom,
            kSecAttrApplicationTag: tag, kSecReturnRef: true, kSecMatchLimit: kSecMatchLimitOne]
        guard SecItemCopyMatching(query as CFDictionary, &value) == errSecSuccess,
              let value, CFGetTypeID(value) == SecKeyGetTypeID() else { return nil }
        return unsafeBitCast(value, to: SecKey.self)
    }
    private func remove(_ tag: Data) {
        SecItemDelete([kSecClass: kSecClassKey, kSecAttrKeyClass: kSecAttrKeyClassPrivate, kSecAttrKeyType: kSecAttrKeyTypeECSECPrimeRandom,
                       kSecAttrApplicationTag: tag] as CFDictionary)
    }
    private func publicData(_ key: SecKey?) -> Data? {
        guard let key, let publicKey = SecKeyCopyPublicKey(key) else { return nil }
        return SecKeyCopyExternalRepresentation(publicKey, nil) as Data?
    }
}
