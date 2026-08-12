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

    static func saveWithUserPresence(
        _ secret: String,
        account: String,
        serviceName: String = service
    ) throws {
        #if os(macOS)
        var accessError: Unmanaged<CFError>?
        guard let access = SecAccessControlCreateWithFlags(
            nil,
            kSecAttrAccessibleWhenUnlockedThisDeviceOnly,
            .userPresence,
            &accessError
        ) else {
            throw KeychainError.accessControlFailed(
                accessError?.takeRetainedValue().localizedDescription ?? ""
            )
        }
        let base: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: serviceName,
            kSecAttrAccount as String: account,
        ]
        SecItemDelete(base as CFDictionary)
        var value = base
        value[kSecValueData as String] = Data(secret.utf8)
        value[kSecAttrAccessControl as String] = access
        let status = SecItemAdd(value as CFDictionary, nil)
        guard status == errSecSuccess else {
            throw KeychainError.writeFailed(status)
        }
        #else
        throw KeychainError.unsupported
        #endif
    }

    static func readWithUserPresence(
        account: String,
        serviceName: String = service,
        reason: String
    ) throws -> String? {
        #if os(macOS)
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: serviceName,
            kSecAttrAccount as String: account,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
            kSecUseOperationPrompt as String: reason,
        ]
        var value: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &value)
        if status == errSecItemNotFound || status == errSecUserCanceled {
            return nil
        }
        guard status == errSecSuccess, let data = value as? Data else {
            throw KeychainError.readFailed(status)
        }
        return String(data: data, encoding: .utf8)
        #else
        throw KeychainError.unsupported
        #endif
    }

    static func exists(
        account: String,
        serviceName: String = service
    ) -> Bool {
        #if os(macOS)
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: serviceName,
            kSecAttrAccount as String: account,
            kSecReturnAttributes as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
            kSecUseAuthenticationUI as String: kSecUseAuthenticationUIFail,
        ]
        return SecItemCopyMatching(query as CFDictionary, nil) == errSecSuccess
        #else
        return false
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
    case readFailed(Int32)
    case accessControlFailed(String)
    case unsupported

    var errorDescription: String? {
        switch self {
        case .writeFailed(let status):
            return L10n.format("Keychain 写入失败（%d）。", status)
        case .readFailed(let status):
            return L10n.format("Keychain 读取失败（%d）。", status)
        case .accessControlFailed(let message):
            return message.isEmpty
                ? L10n.text("无法建立用户在场保护") : message
        case .unsupported:
            return L10n.text("此平台不支持本地 Keychain。")
        }
    }
}
