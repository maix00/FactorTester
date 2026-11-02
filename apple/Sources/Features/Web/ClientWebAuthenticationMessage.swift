import Foundation

/// Authentication requests emitted by the Manager Web shell while embedded
/// in FTClient. Credentials never cross the JavaScript bridge; Web only asks
/// the native app to synchronize or clear its shared session.
enum ClientWebAuthenticationMessage {
    static let handlerName = "tradeResearchAuthentication"

    enum Action: String {
        case logout
        case sessionUpdated = "session-updated"
    }

    static func authorizedAction(from body: Any, isMainFrame: Bool, scheme: String,
                                 host: String, port: Int, endpoint: URL?, currentEndpoint: URL?) -> Action? {
        guard isMainFrame, endpoint == currentEndpoint,
              LocalResearchBridgeContract.sameOrigin(scheme: scheme, host: host, port: port, endpoint: endpoint) else { return nil }
        return action(from: body)
    }

    static func action(from body: Any) -> Action? {
        guard let payload = body as? [String: Any],
              let value = payload["action"] as? String else { return nil }
        return Action(rawValue: value)
    }
}
