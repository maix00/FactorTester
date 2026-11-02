import Foundation
import Combine
import CryptoKit

/// Native mirror of the selected Manager's verified Keycloak Web session.
/// Login, account creation and password changes belong to the Web/Keycloak flow.
@MainActor
final class SessionStore: ObservableObject {
    typealias ClientSessionBridge = @MainActor (String) async -> Bool
    typealias ClientSessionClearer = @MainActor (URL?) async -> Void

    @Published private(set) var user: UserInfo?
    @Published private(set) var isManagerLoggedIn = false
    @Published private(set) var isWorking = false
    @Published var lastError: String?

    private let api: any SessionAPI
    private let bridgeOverride: ClientSessionBridge?
    private let clearClientSession: ClientSessionClearer
    private let clearNativeSession: ClientSessionClearer
    private let managerTokenReader: (URL?) -> String
    private let cliSessionBridge = ClientSessionBridgeCoordinator()
    private var authenticationGeneration: UInt64 = 0

    init(api: any SessionAPI = APIClient.shared,
         bridge: ClientSessionBridge? = nil,
         managerTokenReader: ((URL?) -> String)? = nil,
         clearClientSession: ClientSessionClearer? = nil,
         clearNativeSession: ClientSessionClearer? = nil) {
        self.api = api
        bridgeOverride = bridge
        self.managerTokenReader = managerTokenReader ?? (bridge == nil
            ? { ManagerSessionTokenStore.read(for: $0) } : { _ in "" })
        self.clearClientSession = clearClientSession ?? (bridge == nil ? { endpoint in
            guard let endpoint else { return }
            _ = try? await ReleaseCommand.runObject([
                "client", "profile", "clear-ui-session", "--server-url", endpoint.absoluteString,
            ], executable: ClientCLIResolution.executable())
        } : { _ in })
        self.clearNativeSession = clearNativeSession ?? (bridge == nil ? { endpoint in
            guard let endpoint else { return }
            ManagerSessionTokenStore.remove(for: endpoint)
            await WebSessionCookieSynchronizer.clearManagerSession(for: endpoint, webView: nil)
        } : { _ in })
    }

    var isLoggedIn: Bool { user?.localResearchIdentity != nil }
    var role: String? { user?.role }

    func refreshCLIClientSession() async -> Bool {
        guard isLoggedIn, let principal = user?.username else { return false }
        return await bridgeClientSession(principalRef: principal, reportError: false)
    }

    /// A transport failure retains the selected Manager's known identity;
    /// an explicit denial clears it. Neither path retries a stored password.
    @discardableResult
    func refresh() async -> Bool {
        let generation = authenticationGeneration
        let endpoint = ManagerConfig.shared.baseURL
        do {
            let candidate = try await api.me()
            guard generation == authenticationGeneration, endpoint == ManagerConfig.shared.baseURL else { return false }
            guard candidate.localResearchIdentity != nil else {
                authenticationGeneration &+= 1
                clearAuthentication()
                return false
            }
            if user?.localResearchIdentity != candidate.localResearchIdentity { authenticationGeneration &+= 1 }
            let ticket = authenticationGeneration
            user = candidate
            isManagerLoggedIn = true
            lastError = nil
            _ = await bridgeClientSession(principalRef: candidate.username ?? "", reportError: false, deduplicate: true)
            return ticket == authenticationGeneration && endpoint == ManagerConfig.shared.baseURL && isLoggedIn
        } catch {
            guard generation == authenticationGeneration, endpoint == ManagerConfig.shared.baseURL else { return false }
            if case APIError.unauthorized = error {
                authenticationGeneration &+= 1
                clearAuthentication()
            } else { lastError = error.localizedDescription }
            return isLoggedIn
        }
    }

    /// Confirm an imported Web session before allowing access to local data.
    /// Concurrent handshakes for the same verified identity can share it.
    @discardableResult
    func confirmWebIdentity() async -> Bool {
        let generation = authenticationGeneration
        let endpoint = ManagerConfig.shared.baseURL
        do {
            let candidate = try await api.me()
            guard endpoint == ManagerConfig.shared.baseURL else { return false }
            guard let identity = candidate.localResearchIdentity else {
                if generation == authenticationGeneration {
                    authenticationGeneration &+= 1
                    clearAuthentication()
                }
                return false
            }
            if generation != authenticationGeneration { return user?.localResearchIdentity == identity }
            if user?.localResearchIdentity != identity { authenticationGeneration &+= 1 }
            user = candidate
            isManagerLoggedIn = true
            lastError = nil
            #if os(macOS)
            if let username = candidate.username, !username.isEmpty {
                let ticket = authenticationGeneration
                Task { @MainActor [weak self] in
                    guard let self, self.authenticationGeneration == ticket,
                          self.user?.localResearchIdentity == identity else { return }
                    _ = await self.bridgeClientSession(principalRef: username, reportError: false, deduplicate: true)
                }
            }
            #endif
            return true
        } catch {
            if generation == authenticationGeneration, endpoint == ManagerConfig.shared.baseURL,
               case APIError.unauthorized = error {
                authenticationGeneration &+= 1
                clearAuthentication()
            }
            return false
        }
    }

    /// Commit a native Manager switch only if the initiating identity has not
    /// changed while the target was checked. The target identity comes from
    /// the target Manager, never from JavaScript.
    func adoptManagerSession(expected: LocalResearchIdentity?, candidate: UserInfo?) -> Bool {
        guard user?.localResearchIdentity == expected else { return false }
        if let candidate {
            guard let expected, let actual = candidate.localResearchIdentity,
                  expected.matchesVerifiedSameRealmIdentity(actual) else { return false }
        }
        authenticationGeneration &+= 1
        isWorking = false
        clearAuthentication()
        user = candidate
        return true
    }

    /// Validate an already-selected Manager without replaying saved passwords.
    /// A denied, unavailable, different stable ID, or same-realm subject change
    /// never retains the old UI identity. Cross-realm identity still needs proof.
    @discardableResult
    func validateManagerChange(expectedIdentity: LocalResearchIdentity?) async -> Bool {
        authenticationGeneration &+= 1
        let generation = authenticationGeneration
        let target = ManagerConfig.shared.baseURL
        isWorking = false
        clearAuthentication()
        guard let expected = expectedIdentity else { return false }
        do {
            let candidate = try await api.me()
            guard generation == authenticationGeneration, target == ManagerConfig.shared.baseURL else { return false }
            guard candidate.isLoggedIn, !candidate.visitorLogin,
                  candidate.authentication != "agent",
                  let actual = candidate.localResearchIdentity,
                  expected.matchesVerifiedSameRealmIdentity(actual) else { return false }
            user = candidate
            return true
        } catch {
            guard generation == authenticationGeneration else { return false }
            return false
        }
    }

    private func clearAuthentication() {
        user = nil
        isManagerLoggedIn = false
    }

    private func bridgeClientSession(
        principalRef: String,
        reportError: Bool = true,
        deduplicate: Bool = false
    ) async -> Bool {
        let ticket = authenticationGeneration
        let endpoint = ManagerConfig.shared.baseURL
        let identity = user?.localResearchIdentity
        // Hash in memory only; credentials never become queue identifiers or logs.
        let token = deduplicate ? managerTokenReader(endpoint) : ""
        if deduplicate && token.isEmpty { return false }
        let key = deduplicate ? SHA256.hash(data: Data(((endpoint?.absoluteString ?? "") + "\0" +
            (identity?.issuer ?? "") + "\0" + (identity?.subject ?? "") + "\0" +
            (identity?.stableID ?? "") + "\0" + token).utf8)).map { String(format: "%02x", $0) }.joined() : nil
        return await cliSessionBridge.submit(key: key, valid: { [weak self] in
            guard let self else { return false }
            return self.authenticationGeneration == ticket && ManagerConfig.shared.baseURL == endpoint &&
                self.user?.localResearchIdentity == identity && self.user?.username == principalRef
        }, operation: { [weak self] in
            guard let self else { return false }
            return await self.performClientSessionBridge(principalRef: principalRef, reportError: reportError)
        })
    }

    private func performClientSessionBridge(principalRef: String, reportError: Bool) async -> Bool {
        if let bridgeOverride {
            return await bridgeOverride(principalRef)
        }
        guard let serverURL = ManagerConfig.shared.baseURL?.absoluteString else {
            lastError = L10n.text("尚未配置服务器地址，请先在设置中填写。")
            return false
        }
        let cookies = (ManagerConfig.shared.baseURL.flatMap { HTTPCookieStorage.shared.cookies(for: $0) } ?? [])
            .filter { $0.name == "ft-manager-session" }.map { cookie in
            var value: [String: Any] = [
                "name": cookie.name,
                "value": cookie.value,
                "domain": cookie.domain,
                "path": cookie.path,
                "secure": cookie.isSecure,
            ]
            if let expires = cookie.expiresDate?.timeIntervalSince1970 {
                value["expires"] = expires
            }
            return value
        }
        var payload: [String: Any] = [
            "cookies": cookies,
            "token": ManagerSessionTokenStore.read(for: ManagerConfig.shared.baseURL),
            "certificate_pem": SelfSignedTrustDelegate.certificatePEM(for: ManagerConfig.shared.baseURL)
        ]
        if let identity = user?.localResearchIdentity {
            payload["binding"] = ["issuer": identity.issuer, "subject": identity.subject,
                                  "identity_id": identity.stableID]
        }
        do {
            _ = try await ReleaseCommand.runObject([
                "client", "profile", "import-ui-session",
                "--server-url", serverURL,
                "--principal-ref", principalRef,
            ], executable: ClientCLIResolution.executable(), stdinJSON: payload)
            return true
        } catch {
            if reportError { lastError = error.localizedDescription }
            return false
        }
    }

    func logout() async {
        authenticationGeneration &+= 1
        let ticket = authenticationGeneration
        let endpoint = ManagerConfig.shared.baseURL
        isWorking = false
        clearAuthentication()
        let clear = clearClientSession
        await cliSessionBridge.invalidateAndClear { await clear(endpoint) }
        guard ticket == authenticationGeneration, endpoint == ManagerConfig.shared.baseURL else { return }
        try? await api.logout()
        guard ticket == authenticationGeneration, endpoint == ManagerConfig.shared.baseURL else { return }
        await clearNativeSession(endpoint)
    }
}
