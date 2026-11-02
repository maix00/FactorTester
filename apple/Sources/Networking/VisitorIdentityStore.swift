import Foundation

/// Stable pseudonymous identity for the anonymous Swift visitor mode.
///
/// This value is deliberately separate from the Manager device key and from
/// account credentials. It only lets a server keep one installation's guest
/// workspaces and jobs isolated from another guest's data.
enum VisitorIdentityStore {
    static let defaultsKey = "traderesearch.visitor.id"
    static let legacyDefaultsKey = "factortester.visitor.id"

    static func current(defaults: UserDefaults = .standard) -> String {
        if let stored = defaults.string(forKey: defaultsKey),
           let uuid = UUID(uuidString: stored) {
            let value = uuid.uuidString.lowercased()
            if value != stored { defaults.set(value, forKey: defaultsKey) }
            return value
        }
        if let stored = defaults.string(forKey: legacyDefaultsKey),
           let uuid = UUID(uuidString: stored) {
            let value = uuid.uuidString.lowercased()
            defaults.set(value, forKey: defaultsKey)
            // Retain the old identity if persisting the replacement failed.
            if defaults.string(forKey: defaultsKey) == value {
                defaults.removeObject(forKey: legacyDefaultsKey)
            }
            return value
        }
        let value = UUID().uuidString.lowercased()
        defaults.set(value, forKey: defaultsKey)
        return value
    }

    static func isValid(_ value: String) -> Bool {
        UUID(uuidString: value.trimmingCharacters(in: .whitespaces)) != nil
    }
}
