import Foundation

/// Authentication requests emitted by the Manager Web shell while embedded
/// in FTClient. Credentials never cross the JavaScript bridge; Web only asks
/// the native app to synchronize or clear its shared session.
enum ClientWebAuthenticationMessage {
    static let handlerName = "factorTesterAuthentication"

    enum Action: String {
        case logout
        case sessionUpdated = "session-updated"
    }

    static func action(from body: Any) -> Action? {
        guard let payload = body as? [String: Any],
              let value = payload["action"] as? String else { return nil }
        return Action(rawValue: value)
    }
}
