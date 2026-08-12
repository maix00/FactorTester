import CryptoKit
import Foundation
import Security

enum ManagerSessionTokenStore {
    private static let service = "com.gtht.factortester.manager"

    static func read(for baseURL: URL? = nil) -> String {
        guard let baseURL = baseURL ?? ManagerConfig.shared.baseURL else { return "" }
        guard let account = account(for: baseURL) else { return "" }
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var result: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess,
              let data = result as? Data,
              let token = String(data: data, encoding: .utf8) else { return "" }
        return token.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    static func save(_ token: String, for baseURL: URL? = nil) {
        guard let baseURL = baseURL ?? ManagerConfig.shared.baseURL,
              let account = account(for: baseURL) else { return }
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
        SecItemDelete(query as CFDictionary)
        guard !token.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
        var item = query
        item[kSecValueData as String] = Data(token.utf8)
        item[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        SecItemAdd(item as CFDictionary, nil)
    }

    static func remove(for baseURL: URL? = nil) {
        guard let baseURL = baseURL ?? ManagerConfig.shared.baseURL,
              let account = account(for: baseURL) else { return }
        SecItemDelete([
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ] as CFDictionary)
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
