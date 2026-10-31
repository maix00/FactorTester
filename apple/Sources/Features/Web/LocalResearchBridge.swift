import Foundation

/// The caller must be the current Manager's main frame. This contract does not
/// grant access by itself; the handler also verifies the native session.
enum LocalResearchBridgeContract {
    static let messageName = "tradeResearchLocalResearch"

    static func sameOrigin(scheme: String, host: String, port: Int, endpoint: URL?) -> Bool {
        guard let endpoint, let expectedScheme = endpoint.scheme?.lowercased(),
              let expectedHost = endpoint.host?.lowercased(),
              ["http", "https"].contains(expectedScheme),
              expectedScheme == scheme.lowercased(), expectedHost == host.lowercased() else { return false }
        let defaultPort = expectedScheme == "https" ? 443 : 80
        return (port == 0 ? defaultPort : port) == (endpoint.port ?? defaultPort)
    }
}

#if os(macOS)
import WebKit

@MainActor
final class LocalResearchBridge: NSObject, WKScriptMessageHandlerWithReply {
    private weak var session: SessionStore?
    private let endpoint: URL

    init(session: SessionStore, endpoint: URL) {
        self.session = session
        self.endpoint = endpoint
    }

    func userContentController(
        _ userContentController: WKUserContentController,
        didReceive message: WKScriptMessage,
        replyHandler: @escaping (Any?, String?) -> Void
    ) {
        let origin = message.frameInfo.securityOrigin
        guard message.name == LocalResearchBridgeContract.messageName,
              message.frameInfo.isMainFrame,
              LocalResearchBridgeContract.sameOrigin(scheme: origin.protocol, host: origin.host,
                                                     port: origin.port, endpoint: endpoint),
              ManagerConfig.shared.baseURL == endpoint,
              let user = session?.user, let identity = user.localResearchIdentity,
              let name = user.username, !name.isEmpty,
              let request = message.body as? [String: Any] else {
            replyHandler(["success": false, "code": "local_research_session_unverified"], nil)
            return
        }
        // `self` is an in-memory owner scope, not a new research Profile.
        // Existing username-bound local Profiles are not automatically adopted.
        let envelope: [String: Any] = [
            "binding": ["issuer": identity.issuer, "identity_id": identity.stableID],
            "profile": ["profile_id": "self", "display_name": user.alias ?? name],
            "request": request,
        ]
        Task { @MainActor [weak self] in
            do {
                try await BundledRuntimeActivator.waitUntilReady()
                guard let self, self.isCurrent(identity) else {
                    replyHandler(["success": false, "code": "local_research_session_changed"], nil)
                    return
                }
                let result = try await ReleaseCommand.runObject(
                    ["client", "local-research-request"],
                    executable: ClientCLIResolution.executable(), stdinJSON: envelope
                )
                guard self.isCurrent(identity) else {
                    replyHandler(["success": false, "code": "local_research_session_changed"], nil)
                    return
                }
                replyHandler(result, nil)
            } catch {
                replyHandler(["success": false, "code": "local_research_bridge_failed"], nil)
            }
        }
    }

    private func isCurrent(_ identity: LocalResearchIdentity) -> Bool {
        ManagerConfig.shared.baseURL == endpoint && session?.user?.localResearchIdentity == identity
    }
}
#endif
