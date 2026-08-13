import Foundation

struct UserLanguagePreference: Equatable, Sendable {
    let language: AppLanguage
    let configured: Bool
}

protocol UserLanguagePreferenceAPI: Sendable {
    func read(principal: String) async throws -> UserLanguagePreference
    func update(language: AppLanguage, principal: String) async throws
}

struct ManagerUserLanguagePreferenceClient: UserLanguagePreferenceAPI {
    private struct Envelope: Decodable {
        struct Preferences: Decodable {
            let language: String
            let configured: Bool?
        }
        let preferences: Preferences
    }

    func read(principal: String) async throws -> UserLanguagePreference {
        let envelope: Envelope = try await request(method: "GET", language: nil)
        return UserLanguagePreference(
            language: AppLanguage(
                rawValue: envelope.preferences.language
            ) ?? .system,
            // Managers predating this additive field treated their value as
            // authoritative. Keep that behavior instead of uploading a local
            // cache to an older server.
            configured: envelope.preferences.configured ?? true
        )
    }

    func update(language: AppLanguage, principal: String) async throws {
        let _: Envelope = try await request(method: "POST", language: language)
    }

    private func request<T: Decodable>(
        method: String,
        language: AppLanguage?
    ) async throws -> T {
        guard let url = ManagerConfig.shared.url(forPath: "/api/client/preferences") else {
            throw APIError.notConfigured
        }
        let token = ManagerSessionTokenStore.read()
        guard !token.isEmpty else { throw APIError.unauthorized("login required") }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        if let language {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONSerialization.data(withJSONObject: [
                "language": language.rawValue,
            ])
        }
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse,
              (200..<300).contains(http.statusCode) else {
            throw APIError.server("language preference request failed")
        }
        return try JSONDecoder().decode(T.self, from: data)
    }
}
