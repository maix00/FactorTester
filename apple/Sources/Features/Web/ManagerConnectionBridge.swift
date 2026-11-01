import Foundation
import WebKit

enum ManagerConnectionBridgeContract {
    static let messageName = "tradeResearchManager"
    static let schema = "tr-manager-bridge:v1"

    static func endpoint(_ raw: String) -> URL? {
        guard raw == raw.trimmingCharacters(in: .whitespacesAndNewlines), raw.utf8.count <= 2048,
              !raw.unicodeScalars.contains(where: { CharacterSet.controlCharacters.contains($0) }),
              var parts = URLComponents(string: raw), let scheme = parts.scheme?.lowercased(),
              ["http", "https"].contains(scheme), let host = parts.host, !host.isEmpty,
              parts.user == nil, parts.password == nil, parts.query == nil, parts.fragment == nil,
              parts.path.isEmpty || parts.path == "/",
              scheme == "https" || ManagerEndpointPolicy.isPrivateNetwork(host) else { return nil }
        let port = parts.port ?? (scheme == "https" ? 443 : 80)
        guard (1...65535).contains(port) else { return nil }
        parts.scheme = scheme
        parts.host = host.lowercased()
        parts.port = port
        parts.path = ""
        return parts.url
    }
}

@MainActor
final class ManagerConnectionBridge: NSObject, WKScriptMessageHandlerWithReply {
    enum ProbeResult { case authorized(UserInfo), handoff(URL), unauthorized, unavailable }
    typealias Probe = (URL, LocalResearchIdentity?, String?) async -> ProbeResult
    typealias Apply = (URL) -> Void
    typealias DeviceRestore = (URL, String?) async -> URL?
    private weak var session: SessionStore?
    private let endpoint: URL
    private let probeOverride: Probe?
    private let apply: Apply
    private let restoreDevice: DeviceRestore
    private var verifiedIdentity: LocalResearchIdentity?
    private var verificationGeneration: UInt64 = 0
    private var switching = false

    init(session: SessionStore, endpoint: URL, probe: Probe? = nil,
         restoreDevice: @escaping DeviceRestore = { target, username in
             guard ManagerDeviceKeyStore.load() != nil else { return nil }
             do {
                 return try await ManagerDeviceAuthenticationService.shared.beginOIDCLogin(endpoint: target, expectedUsername: username)
             } catch { return nil }
         }, apply: @escaping Apply = { target in
        guard let scheme = target.scheme, let host = target.host, let port = target.port else { return }
        ManagerConfig.shared.save(scheme: scheme, host: host, port: String(port), serverID: "")
    }) {
        self.session = session
        self.endpoint = endpoint
        self.probeOverride = probe
        self.restoreDevice = restoreDevice
        self.apply = apply
    }

    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage,
                               replyHandler: @escaping (Any?, String?) -> Void) {
        let origin = message.frameInfo.securityOrigin
        guard message.name == ManagerConnectionBridgeContract.messageName, message.frameInfo.isMainFrame,
              LocalResearchBridgeContract.sameOrigin(scheme: origin.protocol, host: origin.host, port: origin.port, endpoint: endpoint),
              ManagerConfig.shared.baseURL == endpoint, let body = message.body as? [String: Any],
              let action = body["action"] as? String, let session else {
            replyHandler(["success": false, "code": "manager_session_changed"], nil)
            return
        }
        if action == "capabilities", Set(body.keys) == ["action"] {
            verificationGeneration &+= 1
            let generation = verificationGeneration
            verifiedIdentity = nil
            let webView = message.webView
            Task { @MainActor [weak self] in
                guard let self else { return }
                if let webView {
                    await WebSessionCookieSynchronizer.importManagerSession(from: webView, endpoint: self.endpoint)
                }
                var confirmed = false
                if ManagerConfig.shared.baseURL == self.endpoint { confirmed = await session.confirmWebIdentity() }
                guard ManagerConfig.shared.baseURL == self.endpoint, generation == self.verificationGeneration else {
                    replyHandler(["success": false, "code": "manager_session_changed"], nil)
                    return
                }
                if confirmed { self.verifiedIdentity = session.user?.localResearchIdentity }
                replyHandler(self.reply(["actions": ["current", "switch", "enroll_device"]]), nil)
            }
            return
        }
        if action == "current", Set(body.keys) == ["action"] {
            let authorized = verifiedIdentity != nil && session.user?.localResearchIdentity == verifiedIdentity
            replyHandler(reply(["url": endpoint.absoluteString,
                                "auth_state": authorized ? "authorized" : "unauthorized"]), nil)
            return
        }
        if action == "enroll_device", Set(body.keys) == ["action"] {
            guard !switching, let identity = verifiedIdentity,
                  session.user?.localResearchIdentity == identity,
                  let username = session.user?.username, !username.isEmpty else {
                replyHandler(["success": false, "code": "manager_session_changed"], nil)
                return
            }
            switching = true
            let generation = verificationGeneration
            let webView = message.webView
            Task { @MainActor [weak self] in
                guard let self else { return }
                defer { self.switching = false }
                if let webView { await WebSessionCookieSynchronizer.importManagerSession(from: webView, endpoint: self.endpoint) }
                guard await session.confirmWebIdentity(), ManagerConfig.shared.baseURL == self.endpoint,
                      session.user?.localResearchIdentity == identity,
                      session.user?.username == username,
                      self.verifiedIdentity == identity, self.verificationGeneration == generation else {
                    replyHandler(["success": false, "code": "manager_session_changed"], nil)
                    return
                }
                do {
                    try await ManagerDeviceRegistryService.shared.enroll(endpoint: self.endpoint, username: username)
                    guard ManagerConfig.shared.baseURL == self.endpoint,
                          session.user?.localResearchIdentity == identity,
                          session.user?.username == username,
                          self.verifiedIdentity == identity, self.verificationGeneration == generation else {
                        replyHandler(["success": false, "code": "manager_session_changed"], nil)
                        return
                    }
                    replyHandler(self.reply([:]), nil)
                } catch {
                    replyHandler(["success": false, "code": "device_enrollment_failed"], nil)
                }
            }
            return
        }
        guard action == "switch", Set(body.keys) == ["action", "url"],
              let raw = body["url"] as? String, let target = ManagerConnectionBridgeContract.endpoint(raw) else {
            replyHandler(["success": false, "code": "manager_invalid_url"], nil)
            return
        }
        guard session.user?.localResearchIdentity == verifiedIdentity else {
            replyHandler(["success": false, "code": "manager_session_changed"], nil)
            return
        }
        guard !switching else {
            replyHandler(["success": false, "code": "manager_switch_pending"], nil)
            return
        }
        switching = true
        let expected = verifiedIdentity
        let generation = verificationGeneration
        let username = session.user?.username
        let webView = message.webView
        Task { @MainActor [weak self] in
            guard let self else { return }
            defer { self.switching = false }
            let result: ProbeResult
            if let probe = self.probeOverride { result = await probe(target, expected, username) }
            else {
                if ManagerSessionTokenStore.read(for: target).isEmpty, let webView {
                    await WebSessionCookieSynchronizer.importManagerSession(from: webView, endpoint: target)
                }
                result = await self.targetSession(target, expected: expected, username: username)
            }
            guard ManagerConfig.shared.baseURL == self.endpoint,
                  session.user?.localResearchIdentity == expected,
                  self.verifiedIdentity == expected, self.verificationGeneration == generation else {
                replyHandler(["success": false, "code": "manager_session_changed"], nil)
                return
            }
            if case .unavailable = result {
                replyHandler(["success": false, "code": "manager_unavailable"], nil)
                return
            }
            let candidate: UserInfo?
            switch result {
            case .authorized(let user): candidate = user
            case .unauthorized, .handoff:
                candidate = nil
                await self.clearTargetSession(target, webView: webView)
            case .unavailable: return
            }
            guard ManagerConfig.shared.baseURL == self.endpoint,
                  self.verifiedIdentity == expected, self.verificationGeneration == generation,
                  session.adoptManagerSession(expected: expected, candidate: candidate) else {
                replyHandler(["success": false, "code": "manager_session_changed"], nil)
                return
            }
            self.apply(target)
            if case .handoff(let url) = result {
                ManagerConfig.shared.queueDeviceLogin(url, for: target)
            }
            #if os(macOS)
            if ManagerConfig.shared.baseURL == target {
                ManagerCLISelectionSynchronizer.shared.schedule(target)
            }
            #endif
            replyHandler(self.reply(["url": raw, "auth_state": candidate == nil ? "unauthorized" : "authorized"]), nil)
        }
    }

    private func targetSession(_ target: URL, expected: LocalResearchIdentity?, username: String?) async -> ProbeResult {
        guard let expected else { return .unauthorized }
        var result = await probe(target, expected: expected)
        if case .unauthorized = result {
            // An enrolled device may authenticate without sending a password.
            if let handoff = await restoreDevice(target, username) { result = .handoff(handoff) }
        }
        return result
    }

    private func probe(_ target: URL, expected: LocalResearchIdentity) async -> ProbeResult {
        guard let host = target.host, let url = URL(string: "/api/session", relativeTo: target)?.absoluteURL else { return .unavailable }
        let config = URLSessionConfiguration.ephemeral
        config.httpCookieStorage = nil
        config.httpShouldSetCookies = false
        config.timeoutIntervalForRequest = 8
        let network = URLSession(configuration: config, delegate: SelfSignedTrustDelegate(allowedHosts: [host], rejectsRedirects: true), delegateQueue: nil)
        defer { network.finishTasksAndInvalidate() }
        var request = URLRequest(url: url)
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        let token = ManagerSessionTokenStore.read(for: target)
        // Other applications may use the same host. Only the Manager's own
        // session cookie belongs in this preflight request.
        let cookies = (HTTPCookieStorage.shared.cookies(for: url) ?? []).filter { $0.name == "ft-manager-session" }
        var usedCookie = token.isEmpty && !cookies.isEmpty
        if !token.isEmpty { request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        else if !cookies.isEmpty {
            request.allHTTPHeaderFields = (request.allHTTPHeaderFields ?? [:]).merging(HTTPCookie.requestHeaderFields(with: cookies)) { old, _ in old }
        }
        do {
            var (data, response) = try await network.data(for: request)
            // A stale endpoint token must not hide a valid Manager cookie.
            if !token.isEmpty, !cookies.isEmpty,
               let http = response as? HTTPURLResponse, http.statusCode == 401 || http.statusCode == 403 {
                request.setValue(nil, forHTTPHeaderField: "Authorization")
                request.allHTTPHeaderFields = (request.allHTTPHeaderFields ?? [:]).merging(HTTPCookie.requestHeaderFields(with: cookies)) { old, _ in old }
                (data, response) = try await network.data(for: request)
                usedCookie = true
            }
            guard let http = response as? HTTPURLResponse else { return .unavailable }
            if http.statusCode == 401 || http.statusCode == 403 { return .unauthorized }
            guard http.statusCode == 200 else { return .unavailable }
            let user = try JSONDecoder().decode(UserInfo.self, from: data)
            guard let actual = user.localResearchIdentity,
                  expected.matchesVerifiedSameRealmIdentity(actual) else { return .unauthorized }
            if usedCookie, let cookie = cookies.first, !cookie.value.isEmpty {
                ManagerSessionTokenStore.save(cookie.value, for: target)
            }
            return .authorized(user)
        } catch { return .unavailable }
    }

    private func clearTargetSession(_ target: URL, webView: WKWebView?) async {
        ManagerSessionTokenStore.remove(for: target)
        guard let host = target.host?.lowercased() else { return }
        func belongs(_ cookie: HTTPCookie) -> Bool {
            let domain = cookie.domain.trimmingCharacters(in: CharacterSet(charactersIn: ".")).lowercased()
            return cookie.name == "ft-manager-session" && (domain == host || host.hasSuffix("." + domain))
        }
        for cookie in HTTPCookieStorage.shared.cookies ?? [] where belongs(cookie) { HTTPCookieStorage.shared.deleteCookie(cookie) }
        if let store = webView?.configuration.websiteDataStore.httpCookieStore {
            let cookies = await withCheckedContinuation { continuation in store.getAllCookies { continuation.resume(returning: $0) } }
            for cookie in cookies where belongs(cookie) { await store.delete(cookie) }
        }
    }

    private func reply(_ values: [String: Any]) -> [String: Any] {
        ["success": true, "schema": ManagerConnectionBridgeContract.schema].merging(values) { _, new in new }
    }
}
