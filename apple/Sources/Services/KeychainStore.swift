import Foundation
#if os(macOS)
import Security
#endif

enum KeychainStore {
    static let service = "com.gtht.client.adapters"

    static func save(
        _ secret: String,
        account: String,
        serviceName: String = service
    ) throws {
        #if os(macOS)
        let base: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: serviceName,
            kSecAttrAccount as String: account,
        ]
        SecItemDelete(base as CFDictionary)
        var value = base
        value[kSecValueData as String] = Data(secret.utf8)
        let status = SecItemAdd(value as CFDictionary, nil)
        guard status == errSecSuccess else {
            throw KeychainError.writeFailed(status)
        }
        #else
        throw KeychainError.unsupported
        #endif
    }

    static func read(
        account: String,
        serviceName: String = service
    ) -> String? {
        #if os(macOS)
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: serviceName,
            kSecAttrAccount as String: account,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var value: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &value) == errSecSuccess,
              let data = value as? Data else { return nil }
        return String(data: data, encoding: .utf8)
        #else
        return nil
        #endif
    }

    static func delete(
        account: String,
        serviceName: String = service
    ) {
        #if os(macOS)
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: serviceName,
            kSecAttrAccount as String: account,
        ]
        SecItemDelete(query as CFDictionary)
        #endif
    }
}

enum KeychainError: LocalizedError {
    case writeFailed(Int32)
    case unsupported

    var errorDescription: String? {
        switch self {
        case .writeFailed(let status):
            return String(
                format: L10n.text("Keychain 写入失败（%d）。"),
                status
            )
        case .unsupported:
            return L10n.text("此平台不支持本地 Keychain。")
        }
    }
}
