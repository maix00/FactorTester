import Foundation

struct SavedSessionCredentials: Codable {
    let username: String
    let password: String
    let serverURL: String
}

enum SessionCredentialStore {
    private static let service = "com.gtht.client.session"
    private static let protectedService = "com.gtht.client.session.user-presence"
    private static let account = "default"

    static func save(
        username: String,
        password: String,
        serverURL: URL?
    ) {
        guard ProcessInfo.processInfo.environment[
            "XCTestConfigurationFilePath"
        ] == nil else { return }
        guard let serverURL,
              let data = try? JSONEncoder().encode(
                SavedSessionCredentials(
                    username: username,
                    password: password,
                    serverURL: serverURL.absoluteString
                )
              ),
              let value = String(data: data, encoding: .utf8) else { return }
        try? KeychainStore.save(
            value,
            account: account,
            serviceName: service
        )
        try? KeychainStore.saveWithUserPresence(
            value,
            account: account,
            serviceName: protectedService
        )
    }

    static func load(serverURL: URL?) -> SavedSessionCredentials? {
        guard ProcessInfo.processInfo.environment[
            "XCTestConfigurationFilePath"
        ] == nil else { return nil }
        guard let serverURL,
              let value = KeychainStore.read(
                account: account,
                serviceName: service
              ),
              let data = value.data(using: .utf8),
              let credentials = try? JSONDecoder().decode(
                SavedSessionCredentials.self,
                from: data
              ),
              credentials.serverURL == serverURL.absoluteString else {
            return nil
        }
        return credentials
    }

    static func hasSavedCredentials(serverURL: URL?) -> Bool {
        load(serverURL: serverURL) != nil
    }

    static func hasUserPresenceCredentials() -> Bool {
        KeychainStore.exists(
            account: account,
            serviceName: protectedService
        )
    }

    static func loadWithUserPresence(
        serverURL: URL?,
        reason: String
    ) throws -> SavedSessionCredentials? {
        guard let serverURL,
              let value = try KeychainStore.readWithUserPresence(
                account: account,
                serviceName: protectedService,
                reason: reason
              ),
              let data = value.data(using: .utf8),
              let credentials = try? JSONDecoder().decode(
                SavedSessionCredentials.self,
                from: data
              ),
              credentials.serverURL == serverURL.absoluteString else {
            return nil
        }
        return credentials
    }

    static func clear() {
        KeychainStore.delete(account: account, serviceName: service)
        KeychainStore.delete(account: account, serviceName: protectedService)
    }
}
