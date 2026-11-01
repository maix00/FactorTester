import CryptoKit
import Foundation
import Security

enum ManagerSessionTokenStore {
    private static let service = "com.gtht.traderesearch.manager"
    private static let legacyService = "com.gtht.factortester.manager"

    static func read(for baseURL: URL? = nil) -> String {
        guard let baseURL = baseURL ?? ManagerConfig.shared.baseURL,
              let account = account(for: baseURL) else { return "" }
        let current = read(service: service, account: account)
        if current.status != errSecItemNotFound { return current.token }
        // Retag in place: this preserves the Keychain access attributes and
        // never exports an existing credential during the migration.
        let old = item(service: legacyService, account: account)
        let status = SecItemUpdate(old as CFDictionary, [
            kSecAttrService as String: service,
            kSecAttrLabel as String: service,
        ] as CFDictionary)
        if status == errSecSuccess || status == errSecDuplicateItem {
            return read(service: service, account: account).token
        }
        // If an OS or access policy prevents retagging, retain the original
        // item and use it only when there is no current entry.
        return read(service: legacyService, account: account).token
    }

    static func save(_ token: String, for baseURL: URL? = nil) {
        guard let baseURL = baseURL ?? ManagerConfig.shared.baseURL,
              let account = account(for: baseURL) else { return }
        guard !token.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            remove(for: baseURL)
            return
        }
        let query = item(service: service, account: account)
        let data = Data(token.utf8)
        var status = SecItemUpdate(query as CFDictionary, [kSecValueData as String: data] as CFDictionary)
        if status == errSecItemNotFound {
            var value = query
            value[kSecValueData as String] = data
            value[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
            value[kSecAttrLabel as String] = service
            status = SecItemAdd(value as CFDictionary, nil)
            if status == errSecDuplicateItem {
                status = SecItemUpdate(query as CFDictionary, [kSecValueData as String: data] as CFDictionary)
            }
        }
        // Never remove the previous credential unless the new value was saved.
        if status == errSecSuccess {
            SecItemDelete(item(service: legacyService, account: account) as CFDictionary)
        }
    }

    static func remove(for baseURL: URL? = nil) {
        guard let baseURL = baseURL ?? ManagerConfig.shared.baseURL,
              let account = account(for: baseURL) else { return }
        for name in [service, legacyService] {
            SecItemDelete(item(service: name, account: account) as CFDictionary)
        }
    }

    private static func item(service: String, account: String) -> [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: service,
         kSecAttrAccount as String: account]
    }

    private static func read(service: String, account: String) -> (status: OSStatus, token: String) {
        var query = item(service: service, account: account)
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        guard status == errSecSuccess, let data = result as? Data,
              let token = String(data: data, encoding: .utf8) else { return (status, "") }
        return (status, token.trimmingCharacters(in: .whitespacesAndNewlines))
    }

    private static func account(for baseURL: URL) -> String? {
        guard var components = URLComponents(url: baseURL, resolvingAgainstBaseURL: false),
              let scheme = components.scheme?.lowercased(),
              let host = components.host?.lowercased(),
              !scheme.isEmpty, !host.isEmpty,
              components.user == nil, components.password == nil,
              components.query == nil, components.fragment == nil else { return nil }
        components.scheme = scheme
        components.host = host
        let normalized = components.url?.absoluteString.trimmingCharacters(
            in: CharacterSet(charactersIn: "/")
        ) ?? baseURL.absoluteString.trimmingCharacters(
            in: CharacterSet(charactersIn: "/")
        )
        let digest = SHA256.hash(data: Data(normalized.utf8))
        return digest.map { String(format: "%02x", $0) }.joined()
    }
}
