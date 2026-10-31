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
    typealias Runner = ([String: Any]) async throws -> [String: Any]
    private weak var session: SessionStore?
    private let endpoint: URL
    private let runner: Runner
    private var boundIdentity: LocalResearchIdentity?
    private var handshakeGeneration: UInt64 = 0

    init(session: SessionStore, endpoint: URL, runner: @escaping Runner = LocalResearchBridge.runRequest) {
        self.session = session
        self.endpoint = endpoint
        self.runner = runner
    }

    private static func runRequest(_ envelope: [String: Any]) async throws -> [String: Any] {
        try await BundledRuntimeActivator.waitUntilReady()
        return try await ReleaseCommand.runObject(
            ["client", "local-research-request"],
            executable: ClientCLIResolution.executable(), stdinJSON: envelope
        )
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
              let request = message.body as? [String: Any] else {
            replyHandler(["success": false, "code": "local_research_session_unverified"], nil)
            return
        }
        let webView = message.webView
        let isHandshake = request["action"] as? String == "capabilities"
        if isHandshake {
            handshakeGeneration &+= 1
            boundIdentity = nil
        }
        let handshake = handshakeGeneration
        Task { @MainActor [weak self] in
            guard let self, let session = self.session else {
                replyHandler(["success": false, "code": "local_research_session_unverified"], nil)
                return
            }
            // OAuth redirects restore the Web cookie asynchronously. Import it
            // and verify /api/session before negotiating local capabilities.
            if isHandshake {
                if let webView {
                    await WebSessionCookieSynchronizer.importManagerSession(from: webView, endpoint: self.endpoint)
                }
                guard ManagerConfig.shared.baseURL == self.endpoint,
                      await session.confirmWebIdentity(), handshake == self.handshakeGeneration else {
                    replyHandler(["success": false, "code": "local_research_session_unverified"], nil)
                    return
                }
            }
            guard let user = session.user, let identity = user.localResearchIdentity,
                  let name = user.username, !name.isEmpty, self.isCurrent(identity) else {
                replyHandler(["success": false, "code": "local_research_session_unverified"], nil)
                return
            }
            if isHandshake {
                self.boundIdentity = identity
            } else if self.boundIdentity != identity {
                replyHandler(["success": false, "code": "local_research_session_unverified"], nil)
                return
            }
            // `self` is an in-memory owner scope, not a new research Profile.
            // Existing username-bound Profiles are not automatically adopted.
            var manager: [String: Any] = ["endpoint": self.endpoint.absoluteString,
                                           "subject": identity.subject,
                                           "token": "", "certificate_pem": "", "cookies": []]
            if ["import_research", "publish_report", "pull_report", "sync_reports"].contains(request["action"] as? String ?? "") {
                let cookies = (HTTPCookieStorage.shared.cookies(for: self.endpoint) ?? [])
                    .filter { $0.name == "ft-manager-session" }.map { cookie -> [String: Any] in
                        var value: [String: Any] = ["name": cookie.name, "value": cookie.value,
                            "domain": cookie.domain, "path": cookie.path, "secure": cookie.isSecure]
                        if let expires = cookie.expiresDate?.timeIntervalSince1970 { value["expires"] = expires }
                        return value
                    }
                manager["token"] = ManagerSessionTokenStore.read(for: self.endpoint)
                manager["certificate_pem"] = SelfSignedTrustDelegate.certificatePEM(for: self.endpoint)
                manager["cookies"] = cookies
            }
            let envelope: [String: Any] = [
                "binding": ["issuer": identity.issuer, "identity_id": identity.stableID],
                "profile": ["profile_id": "self", "display_name": user.alias ?? name],
                "request": request, "manager": manager,
            ]
            do {
                guard self.isCurrent(identity), self.boundIdentity == identity,
                      handshake == self.handshakeGeneration else {
                    replyHandler(["success": false, "code": "local_research_session_changed"], nil)
                    return
                }
                let result = try await self.runner(envelope)
                guard self.isCurrent(identity), self.boundIdentity == identity,
                      handshake == self.handshakeGeneration else {
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
