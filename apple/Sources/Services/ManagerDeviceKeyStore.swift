import Foundation
import Security

/// A native Manager device identity.
///
/// The private key is a permanent Keychain key and is never exported. On
/// hardware that supports it, creation first attempts the Secure Enclave and
/// falls back to a device-only Keychain key when the platform does not expose
/// an enclave (for example, some development Macs and simulators).
struct ManagerDeviceCredential: Codable, Equatable {
    let deviceID: String
    let username: String
    let publicKey: [String: String]
    let secureEnclave: Bool
}

enum ManagerDeviceKeyStoreError: LocalizedError {
    case invalidPublicKey
    case keyCreationFailed(String)
    case keyUnavailable
    case signingFailed(String)

    var errorDescription: String? {
        switch self {
        case .invalidPublicKey:
            return L10n.text("原生设备公钥格式无效。")
        case .keyCreationFailed(let message):
            return message.isEmpty
                ? L10n.text("无法创建原生设备密钥。") : message
        case .keyUnavailable:
            return L10n.text("原生设备密钥不可用。")
        case .signingFailed(let message):
            return message.isEmpty
                ? L10n.text("原生设备签名失败。") : message
        }
    }
}

/// Keychain/Secure Enclave storage used by the Swift client instead of
/// browser IndexedDB. The server receives only `publicKey` and signatures.
enum ManagerDeviceKeyStore {
    private static let keyTagPrefix = "com.gtht.traderesearch.device-key."
    private static let legacyKeyTagPrefix = "com.gtht.factortester.device-key."
    private static let metadataService = "com.gtht.traderesearch.device"
    private static let legacyMetadataService = "com.gtht.factortester.device"
    private static let metadataAccount = "current"
    private static let currentDeviceIDKey = "traderesearch.manager.device.id"
    private static let legacyDeviceIDKey = "factortester.manager.device.id"

    static func create(
        deviceID: String = UUID().uuidString,
        username: String = ""
    ) throws -> ManagerDeviceCredential {
        delete()
        let tag = Data((keyTagPrefix + deviceID).utf8)
        var secureEnclave = true
        let privateKey: SecKey
        do {
            privateKey = try makeKey(tag: tag, secureEnclave: true)
        } catch {
            secureEnclave = false
            privateKey = try makeKey(tag: tag, secureEnclave: false)
        }
        guard let publicKey = SecKeyCopyPublicKey(privateKey),
              let jwk = try? publicJWK(for: publicKey) else {
            deleteKey(tag: tag)
            throw ManagerDeviceKeyStoreError.invalidPublicKey
        }
        let credential = ManagerDeviceCredential(
            deviceID: deviceID,
            username: username,
            publicKey: jwk,
            secureEnclave: secureEnclave
        )
        do {
            try saveMetadata(credential)
        } catch {
            deleteKey(tag: tag)
            throw error
        }
        UserDefaults.standard.set(deviceID, forKey: currentDeviceIDKey)
        return credential
    }

    static func load() -> ManagerDeviceCredential? {
        guard let data = readMetadata(),
              let credential = try? JSONDecoder().decode(
                ManagerDeviceCredential.self, from: data
              ) else { return nil }
        guard resolveKey(credential: credential) != nil else { return nil }
        UserDefaults.standard.set(credential.deviceID, forKey: currentDeviceIDKey)
        UserDefaults.standard.removeObject(forKey: legacyDeviceIDKey)
        return credential
    }

    static func updateUsername(_ username: String) throws {
        guard var credential = load() else {
            throw ManagerDeviceKeyStoreError.keyUnavailable
        }
        credential = ManagerDeviceCredential(
            deviceID: credential.deviceID,
            username: username,
            publicKey: credential.publicKey,
            secureEnclave: credential.secureEnclave
        )
        try saveMetadata(credential)
    }

    static func sign(_ message: Data) throws -> Data {
        guard let credential = load() else {
            throw ManagerDeviceKeyStoreError.keyUnavailable
        }
        guard let privateKey = resolveKey(credential: credential) else {
            throw ManagerDeviceKeyStoreError.keyUnavailable
        }
        var error: Unmanaged<CFError>?
        guard let der = SecKeyCreateSignature(
            privateKey,
            .ecdsaSignatureMessageX962SHA256,
            message as CFData,
            &error
        ) as Data? else {
            throw ManagerDeviceKeyStoreError.signingFailed(
                error?.takeRetainedValue().localizedDescription ?? ""
            )
        }
        return try p1363Signature(fromDER: der)
    }

    static func delete() {
        guard let credential = loadMetadata() else {
            UserDefaults.standard.removeObject(forKey: currentDeviceIDKey)
            UserDefaults.standard.removeObject(forKey: legacyDeviceIDKey)
            return
        }
        // Do not delete a colliding key belonging to a different public identity.
        for prefix in [keyTagPrefix, legacyKeyTagPrefix] {
            let tag = Data((prefix + credential.deviceID).utf8)
            if let key = loadKey(tag: tag), matches(key: key, publicKey: credential.publicKey) {
                deleteKey(tag: tag)
            }
        }
        deleteMetadata()
        UserDefaults.standard.removeObject(forKey: currentDeviceIDKey)
        UserDefaults.standard.removeObject(forKey: legacyDeviceIDKey)
    }

    private static func resolveKey(credential: ManagerDeviceCredential) -> SecKey? {
        let current = Data((keyTagPrefix + credential.deviceID).utf8)
        let legacy = Data((legacyKeyTagPrefix + credential.deviceID).utf8)
        return migrateKey(currentTag: current, legacyTag: legacy, publicKey: credential.publicKey)
    }

    /// Move the Keychain tag in place; a Secure Enclave private key is never
    /// exported or regenerated. Failure leaves the verified old key usable.
    static func migrateKey(currentTag: Data, legacyTag: Data, publicKey: [String: String]) -> SecKey? {
        if let current = loadKey(tag: currentTag) {
            return matches(key: current, publicKey: publicKey) ? current : nil
        }
        guard let legacy = loadKey(tag: legacyTag), matches(key: legacy, publicKey: publicKey) else { return nil }
        let query: [CFString: Any] = [kSecClass: kSecClassKey, kSecAttrKeyClass: kSecAttrKeyClassPrivate,
            kSecAttrKeyType: kSecAttrKeyTypeECSECPrimeRandom, kSecAttrApplicationTag: legacyTag]
        let status = SecItemUpdate(query as CFDictionary, [kSecAttrApplicationTag: currentTag] as CFDictionary)
        if status == errSecSuccess || status == errSecItemNotFound || status == errSecDuplicateItem {
            if let current = loadKey(tag: currentTag), matches(key: current, publicKey: publicKey) { return current }
        }
        // A failed retag must never cause a different key to be substituted.
        if let unchanged = loadKey(tag: legacyTag), matches(key: unchanged, publicKey: publicKey) { return unchanged }
        // The original SecKey remains valid for this operation if a successful
        // retag cannot immediately be queried. Keep its identity unchanged.
        return status == errSecSuccess ? legacy : nil
    }

    private static func matches(key: SecKey, publicKey: [String: String]) -> Bool {
        guard let publicPart = SecKeyCopyPublicKey(key), let jwk = try? publicJWK(for: publicPart) else { return false }
        return jwk == publicKey
    }

    private static func makeKey(tag: Data, secureEnclave: Bool) throws -> SecKey {
        var accessError: Unmanaged<CFError>?
        guard let access = SecAccessControlCreateWithFlags(
            nil,
            kSecAttrAccessibleWhenUnlockedThisDeviceOnly,
            .privateKeyUsage,
            &accessError
        ) else {
            throw ManagerDeviceKeyStoreError.keyCreationFailed(
                accessError?.takeRetainedValue().localizedDescription ?? ""
            )
        }
        var attributes: [CFString: Any] = [
            kSecAttrKeyType: kSecAttrKeyTypeECSECPrimeRandom,
            kSecAttrKeySizeInBits: 256,
            kSecAttrIsPermanent: true,
            kSecAttrApplicationTag: tag,
            kSecAttrAccessControl: access,
        ]
        if secureEnclave {
            attributes[kSecAttrTokenID] = kSecAttrTokenIDSecureEnclave
        }
        var error: Unmanaged<CFError>?
        guard let key = SecKeyCreateRandomKey(attributes as CFDictionary, &error) else {
            throw ManagerDeviceKeyStoreError.keyCreationFailed(
                error?.takeRetainedValue().localizedDescription ?? ""
            )
        }
        return key
    }

    private static func loadKey(tag: Data) -> SecKey? {
        let query: [CFString: Any] = [
            kSecClass: kSecClassKey,
            kSecAttrKeyClass: kSecAttrKeyClassPrivate,
            kSecAttrKeyType: kSecAttrKeyTypeECSECPrimeRandom,
            kSecAttrApplicationTag: tag,
            kSecReturnRef: true,
            kSecMatchLimit: kSecMatchLimitOne,
        ]
        var result: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess else {
            return nil
        }
        guard let result, CFGetTypeID(result) == SecKeyGetTypeID() else {
            return nil
        }
        return unsafeBitCast(result, to: SecKey.self)
    }

    private static func deleteKey(tag: Data) {
        SecItemDelete([
            kSecClass: kSecClassKey,
            kSecAttrKeyClass: kSecAttrKeyClassPrivate,
            kSecAttrKeyType: kSecAttrKeyTypeECSECPrimeRandom,
            kSecAttrApplicationTag: tag,
        ] as CFDictionary)
    }

    static func publicJWK(for key: SecKey) throws -> [String: String] {
        var error: Unmanaged<CFError>?
        guard let data = SecKeyCopyExternalRepresentation(key, &error) as Data?,
              data.count == 65, data.first == 0x04 else {
            throw ManagerDeviceKeyStoreError.invalidPublicKey
        }
        return [
            "kty": "EC",
            "crv": "P-256",
            "x": base64URL(data[1..<33]),
            "y": base64URL(data[33..<65]),
        ]
    }

    private static func p1363Signature(fromDER der: Data) throws -> Data {
        let bytes = [UInt8](der)
        guard bytes.count > 6, bytes[0] == 0x30 else {
            throw ManagerDeviceKeyStoreError.signingFailed("invalid DER signature")
        }
        var index = 2
        guard bytes[index] == 0x02 else {
            throw ManagerDeviceKeyStoreError.signingFailed("invalid DER signature")
        }
        let rLength = Int(bytes[index + 1]); index += 2
        guard index + rLength + 2 <= bytes.count else {
            throw ManagerDeviceKeyStoreError.signingFailed("invalid DER signature")
        }
        let r = Array(bytes[index..<(index + rLength)]); index += rLength
        guard bytes[index] == 0x02 else {
            throw ManagerDeviceKeyStoreError.signingFailed("invalid DER signature")
        }
        let sLength = Int(bytes[index + 1]); index += 2
        guard index + sLength <= bytes.count else {
            throw ManagerDeviceKeyStoreError.signingFailed("invalid DER signature")
        }
        let s = Array(bytes[index..<(index + sLength)])
        guard r.count <= 33, s.count <= 33,
              !r.isEmpty, !s.isEmpty,
              (r.count == 32 || (r.count == 33 && r[0] == 0)),
              (s.count == 32 || (s.count == 33 && s[0] == 0)) else {
            throw ManagerDeviceKeyStoreError.signingFailed("invalid DER signature")
        }
        return Data(integer: r, width: 32) + Data(integer: s, width: 32)
    }

    private static func base64URL(_ bytes: Data.SubSequence) -> String {
        Data(bytes).base64EncodedString()
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
    }

    private static func loadMetadata() -> ManagerDeviceCredential? {
        guard let data = readMetadata() else { return nil }
        return try? JSONDecoder().decode(ManagerDeviceCredential.self, from: data)
    }

    /// The same generic-password migration is also exercised with isolated
    /// test service/account names; the real device entry is never needed.
    static func readMetadata(service: String = metadataService, legacy: String = legacyMetadataService,
                             account: String = metadataAccount) -> Data? {
        func item(_ name: String) -> [CFString: Any] {
            [kSecClass: kSecClassGenericPassword, kSecAttrService: name, kSecAttrAccount: account]
        }
        func read(_ name: String) -> (OSStatus, Data?) {
            var query = item(name)
            query[kSecReturnData] = true
            query[kSecMatchLimit] = kSecMatchLimitOne
            var result: CFTypeRef?
            let status = SecItemCopyMatching(query as CFDictionary, &result)
            return (status, result as? Data)
        }
        let current = read(service)
        if current.0 == errSecSuccess, let currentData = current.1 {
            let previous = read(legacy)
            if previous.0 == errSecSuccess, let previousData = previous.1 {
                guard let a = try? JSONDecoder().decode(ManagerDeviceCredential.self, from: currentData),
                      let b = try? JSONDecoder().decode(ManagerDeviceCredential.self, from: previousData),
                      a.deviceID == b.deviceID, a.publicKey == b.publicKey else { return nil }
            } else if previous.0 != errSecItemNotFound { return nil }
            return currentData
        }
        guard current.0 == errSecItemNotFound else { return nil }
        let result = SecItemUpdate(item(legacy) as CFDictionary,
            [kSecAttrService: service, kSecAttrLabel: service] as CFDictionary)
        if result == errSecSuccess || result == errSecDuplicateItem { return read(service).1 }
        return read(legacy).1
    }

    private static func saveMetadata(_ credential: ManagerDeviceCredential) throws {
        let data = try JSONEncoder().encode(credential)
        // Refuse to overwrite either namespace if it identifies another device.
        for service in [metadataService, legacyMetadataService] {
            let query: [CFString: Any] = [kSecClass: kSecClassGenericPassword,
                kSecAttrService: service, kSecAttrAccount: metadataAccount,
                kSecReturnData: true, kSecMatchLimit: kSecMatchLimitOne]
            var value: CFTypeRef?
            let existingStatus = SecItemCopyMatching(query as CFDictionary, &value)
            if existingStatus == errSecItemNotFound { continue }
            guard existingStatus == errSecSuccess, let bytes = value as? Data,
                  let existing = try? JSONDecoder().decode(ManagerDeviceCredential.self, from: bytes),
                  existing.deviceID == credential.deviceID, existing.publicKey == credential.publicKey else {
                throw ManagerDeviceKeyStoreError.keyCreationFailed("Conflicting Keychain device identity")
            }
        }
        let base: [CFString: Any] = [kSecClass: kSecClassGenericPassword,
            kSecAttrService: metadataService, kSecAttrAccount: metadataAccount]
        var status = SecItemUpdate(base as CFDictionary, [kSecValueData: data] as CFDictionary)
        if status == errSecItemNotFound {
            var item = base
            item[kSecValueData] = data
            item[kSecAttrAccessible] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
            item[kSecAttrLabel] = metadataService
            status = SecItemAdd(item as CFDictionary, nil)
            if status == errSecDuplicateItem {
                status = SecItemUpdate(base as CFDictionary, [kSecValueData: data] as CFDictionary)
            }
        }
        guard status == errSecSuccess else {
            throw ManagerDeviceKeyStoreError.keyCreationFailed("Keychain metadata write failed")
        }
        // An unrelated pre-existing legacy device must not be removed.
        let legacyQuery: [CFString: Any] = [kSecClass: kSecClassGenericPassword,
            kSecAttrService: legacyMetadataService, kSecAttrAccount: metadataAccount,
            kSecReturnData: true, kSecMatchLimit: kSecMatchLimitOne]
        var previous: CFTypeRef?
        if SecItemCopyMatching(legacyQuery as CFDictionary, &previous) == errSecSuccess,
           let previousData = previous as? Data,
           let old = try? JSONDecoder().decode(ManagerDeviceCredential.self, from: previousData),
           old.deviceID == credential.deviceID, old.publicKey == credential.publicKey {
            SecItemDelete([kSecClass: kSecClassGenericPassword, kSecAttrService: legacyMetadataService,
                           kSecAttrAccount: metadataAccount] as CFDictionary)
        }
    }

    private static func deleteMetadata() {
        for service in [metadataService, legacyMetadataService] {
            SecItemDelete([kSecClass: kSecClassGenericPassword, kSecAttrService: service,
                           kSecAttrAccount: metadataAccount] as CFDictionary)
        }
    }

}

private extension Data {
    init(integer bytes: [UInt8], width: Int) {
        var value = bytes
        while value.first == 0 { value.removeFirst() }
        if value.count > width { value = Array(value.suffix(width)) }
        self.init(repeating: 0, count: width - value.count)
        append(contentsOf: value)
    }
}
