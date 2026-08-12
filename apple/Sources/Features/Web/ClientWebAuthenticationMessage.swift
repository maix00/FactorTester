import Foundation

/// Authentication requests emitted by the Manager Web shell while embedded
/// in FTClient. Credentials never cross the JavaScript bridge; Web only asks
/// the native app to present or clear its shared Keychain-backed session.
enum ClientWebAuthenticationMessage {
    static let handlerName = "factorTesterAuthentication"

    enum Action: String {
        case open
        case logout
    }

    static func action(from body: Any) -> Action? {
        guard let payload = body as? [String: Any],
              let value = payload["action"] as? String else { return nil }
        return Action(rawValue: value)
    }
}
