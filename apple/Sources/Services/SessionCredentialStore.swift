import Foundation

struct SavedSessionCredentials: Codable {
    let username: String
    let password: String
    let serverURL: String?
}

enum SessionCredentialStore {
    private static let service = "com.gtht.client.session"
    private static let protectedService = "com.gtht.client.session.user-presence"
    private static let account = "default"

    @discardableResult
    static func save(
        username: String,
        password: String
    ) -> Bool {
        guard ProcessInfo.processInfo.environment[
            "XCTestConfigurationFilePath"
        ] == nil else { return true }
        guard let data = try? JSONEncoder().encode(
                SavedSessionCredentials(
                    username: username,
                    password: password,
                    serverURL: nil
                )
              ),
              let value = String(data: data, encoding: .utf8) else { return false }
        return persist(value, username: username, password: password)
    }

    static func load() -> SavedSessionCredentials? {
        guard ProcessInfo.processInfo.environment[
            "XCTestConfigurationFilePath"
        ] == nil else { return nil }
        return decode(
            KeychainStore.read(account: account, serviceName: service)
        )
    }

    static func hasSavedCredentials() -> Bool {
        load() != nil
    }

    static func hasUserPresenceCredentials() -> Bool {
        KeychainStore.exists(
            account: account,
            serviceName: protectedService
        )
    }

    static func loadWithUserPresence(
        reason: String
    ) throws -> SavedSessionCredentials? {
        guard let value = try KeychainStore.readWithUserPresence(
            account: account,
            serviceName: protectedService,
            reason: reason
        ) else { return nil }
        return decode(value)
    }

    static func clear() {
        KeychainStore.delete(account: account, serviceName: service)
        KeychainStore.delete(account: account, serviceName: protectedService)
    }

    private static func decode(_ value: String?) -> SavedSessionCredentials? {
        guard let value,
              let data = value.data(using: .utf8),
              let credentials = try? JSONDecoder().decode(
                SavedSessionCredentials.self,
                from: data
              ) else {
            return nil
        }
        return credentials
    }

    private static func persist(
        _ value: String,
        username: String,
        password: String
    ) -> Bool {
        do {
            try KeychainStore.save(value, account: account, serviceName: service)
        } catch {
            return false
        }
        // Touch ID is an optional second copy. A machine without biometric
        // enrollment must not make the ordinary restart-safe credential fail.
        try? KeychainStore.saveWithUserPresence(
                value,
                account: account,
                serviceName: protectedService
            )
        guard let saved = load() else { return false }
        return saved.username == username && saved.password == password
    }
}
