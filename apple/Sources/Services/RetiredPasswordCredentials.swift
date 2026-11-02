import Foundation

/// Removal only: never decode, copy or replay the retired password credentials.
enum RetiredPasswordCredentials {
    static func remove(delete: (String, String) -> Void = { account, service in
        KeychainStore.delete(account: account, serviceName: service)
    }) {
        for service in ["com.gtht.client.session", "com.gtht.client.session.user-presence"] {
            delete("default", service)
        }
    }
}
