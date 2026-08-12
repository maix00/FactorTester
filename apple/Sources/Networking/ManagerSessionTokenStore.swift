import CryptoKit
import Foundation
import Security

enum ManagerSessionTokenStore {
    private static let service = "com.gtht.factortester.manager"

    static func read() -> String {
        guard let baseURL = ManagerConfig.shared.baseURL else { return "" }
        let normalized = baseURL.absoluteString.trimmingCharacters(
            in: CharacterSet(charactersIn: "/")
        )
        let digest = SHA256.hash(data: Data(normalized.utf8))
        let account = digest.map { String(format: "%02x", $0) }.joined()
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
}

