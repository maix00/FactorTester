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
    private static let keyTagPrefix = "com.gtht.factortester.device-key."
    private static let metadataService = "com.gtht.factortester.device"
    private static let metadataAccount = "current"
    private static let currentDeviceIDKey = "factortester.manager.device.id"

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
        try saveMetadata(credential)
        UserDefaults.standard.set(deviceID, forKey: currentDeviceIDKey)
        return credential
    }

    static func load() -> ManagerDeviceCredential? {
        guard let data = readMetadata(),
              let credential = try? JSONDecoder().decode(
                ManagerDeviceCredential.self, from: data
              ) else { return nil }
        let tag = Data((keyTagPrefix + credential.deviceID).utf8)
        guard loadKey(tag: tag) != nil else { return nil }
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
        let tag = Data((keyTagPrefix + credential.deviceID).utf8)
        guard let privateKey = loadKey(tag: tag) else {
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
            return
        }
        deleteKey(tag: Data((keyTagPrefix + credential.deviceID).utf8))
        deleteMetadata()
        UserDefaults.standard.removeObject(forKey: currentDeviceIDKey)
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
            kSecAttrKeyType: kSecAttrKeyTypeECSECPrimeRandom,
            kSecAttrApplicationTag: tag,
        ] as CFDictionary)
    }

    private static func publicJWK(for key: SecKey) throws -> [String: String] {
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

    private static func readMetadata() -> Data? {
        let query: [CFString: Any] = [
            kSecClass: kSecClassGenericPassword,
            kSecAttrService: metadataService,
            kSecAttrAccount: metadataAccount,
            kSecReturnData: true,
            kSecMatchLimit: kSecMatchLimitOne,
        ]
        var result: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess else {
            return nil
        }
        return result as? Data
    }

    private static func saveMetadata(_ credential: ManagerDeviceCredential) throws {
        let data = try JSONEncoder().encode(credential)
        let base: [CFString: Any] = [
            kSecClass: kSecClassGenericPassword,
            kSecAttrService: metadataService,
            kSecAttrAccount: metadataAccount,
        ]
        SecItemDelete(base as CFDictionary)
        var item = base
        item[kSecValueData] = data
        item[kSecAttrAccessible] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        guard SecItemAdd(item as CFDictionary, nil) == errSecSuccess else {
            throw ManagerDeviceKeyStoreError.keyCreationFailed("Keychain metadata write failed")
        }
    }

    private static func deleteMetadata() {
        SecItemDelete([
            kSecClass: kSecClassGenericPassword,
            kSecAttrService: metadataService,
            kSecAttrAccount: metadataAccount,
        ] as CFDictionary)
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
