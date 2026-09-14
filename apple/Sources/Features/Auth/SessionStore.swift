import Foundation
import Combine

enum ManagerDeviceSessionRestore: Equatable {
    case notRequired
    case authenticated(username: String)
}

/// 全局登录态 —— 包装 `/api/me`、`/login`、`/logout`，供整个 App 观察。
@MainActor
final class SessionStore: ObservableObject {
    typealias ClientSessionBridge = @MainActor (String) async -> Bool
    typealias CredentialLoader = () -> SavedSessionCredentials?
    typealias CredentialSaver = (String, String) -> Bool
    typealias ManagerDeviceSessionRestorer = (
        String
    ) async throws -> ManagerDeviceSessionRestore

    @Published private(set) var user: UserInfo?
    @Published private(set) var isManagerLoggedIn = false
    @Published private(set) var isWorking = false
    @Published var lastError: String?

    private let api: any SessionAPI
    private let managerAPI: any ManagerSessionAPI
    private let bridgeOverride: ClientSessionBridge?
    private let credentialLoader: CredentialLoader
    private let credentialSaver: CredentialSaver
    private let managerDeviceSessionRestorer: ManagerDeviceSessionRestorer
    private var restoreTask: Task<Bool, Never>?

    init(
        api: any SessionAPI = APIClient.shared,
        managerAPI: any ManagerSessionAPI = ManagerCLIClient.shared,
        bridge: ClientSessionBridge? = nil,
        credentialLoader: @escaping CredentialLoader = SessionCredentialStore.load,
        credentialSaver: @escaping CredentialSaver = SessionCredentialStore.save,
        managerDeviceSessionRestorer: @escaping ManagerDeviceSessionRestorer =
            SessionStore.restoreConfiguredPublicManagerDeviceSession
    ) {
        self.api = api
        self.managerAPI = managerAPI
        bridgeOverride = bridge
        self.credentialLoader = credentialLoader
        self.credentialSaver = credentialSaver
        self.managerDeviceSessionRestorer = managerDeviceSessionRestorer
    }

    var isLoggedIn: Bool { user?.isLoggedIn ?? false }
    var role: String? { user?.role }

    /// 将原生 UI 的登录 Cookie 同步到 CLI，使设置页的 CLI 操作复用同一登录态
    func refreshCLIClientSession() async -> Bool {
        guard let principalRef = user?.username, !principalRef.isEmpty else {
            return false
        }
        return await bridgeClientSession(
            principalRef: principalRef,
            reportError: false
        )
    }

    /// 启动 / 设置变更后刷新当前登录态。
    @discardableResult
    func refresh() async -> Bool {
        do {
            let refreshed = try await api.me()
            // Some server versions answer `/api/me` with HTTP 200 and an
            // empty identity after a restart instead of returning 401.  It
            // is still an expired cookie, so try the Keychain credentials
            // before exposing a logged-out screen.
            guard refreshed.isLoggedIn else {
                if await restoreSavedSessionWithRetry() { return true }
                user = refreshed
                isManagerLoggedIn = false
                return false
            }
            var confirmed = refreshed
            if !confirmed.keepLogin {
                do {
                    confirmed = try await confirmPersistentSession()
                } catch {
                    if await restoreSavedSessionWithRetry() { return true }
                    lastError = L10n.format(
                        "登录会话未能持久化：%@",
                        error.localizedDescription
                    )
                    clearAuthentication()
                    return false
                }
            }
            user = confirmed
            try? CanonicalFactorLibraryAccessStore.ensureDefault(
                for: confirmed.username ?? ""
            )
            _ = await bridgeClientSession(
                principalRef: confirmed.username ?? "",
                reportError: false
            )
            await refreshManagerSession()
            if !refreshed.isLoggedIn { isManagerLoggedIn = false }
            return refreshed.isLoggedIn
        } catch let error as APIError {
            if case .unauthorized = error {
                if await restoreSavedSessionWithRetry() { return true }
                user = nil
                isManagerLoggedIn = false
            } else {
                lastError = error.localizedDescription
            }
            return isLoggedIn
        } catch {
            // 网络抖动、服务器升级或详情接口故障不应被解释成登出。
            lastError = error.localizedDescription
            return isLoggedIn
        }
    }

    private func seedUser(from response: AuthResponse, fallbackUsername: String) {
        user = UserInfo(
            username: response.username ?? fallbackUsername,
            alias: response.alias,
            role: response.role,
            isAdmin: response.isAdmin ?? false,
            keepLogin: true
        )
    }

    private func clearAuthentication() {
        user = nil
        isManagerLoggedIn = false
    }

    func login(username: String, password: String) async -> Bool {
        isWorking = true; lastError = nil
        defer { isWorking = false }
        do {
            let resp = try await api.login(
                username: username,
                password: password
            )
            if resp.success {
                seedUser(from: resp, fallbackUsername: username)
                try? CanonicalFactorLibraryAccessStore.ensureDefault(
                    for: resp.username ?? username
                )
                return await completeAuthentication(
                    principalRef: resp.username ?? username,
                    username: username,
                    password: password
                )
            } else {
                lastError = resp.error ?? L10n.text("登录失败")
                return false
            }
        } catch {
            lastError = (error as? APIError)?.errorDescription ?? error.localizedDescription
            return false
        }
    }

    private func bridgeClientSession(
        principalRef: String,
        reportError: Bool = true
    ) async -> Bool {
        if let bridgeOverride {
            return await bridgeOverride(principalRef)
        }
        guard let serverURL = ManagerConfig.shared.baseURL?.absoluteString else {
            lastError = L10n.text("尚未配置服务器地址，请先在设置中填写。")
            return false
        }
        let cookies = (HTTPCookieStorage.shared.cookies ?? []).map { cookie in
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
        do {
            _ = try await ReleaseCommand.runObject([
                "client", "profile", "import-ui-session",
                "--server-url", serverURL,
                "--principal-ref", principalRef,
            ], executable: ClientCLIResolution.executable(), stdinJSON: [
                "cookies": cookies,
                "token": ManagerSessionTokenStore.read(for: ManagerConfig.shared.baseURL),
                "certificate_pem": SelfSignedTrustDelegate.certificatePEM(for: ManagerConfig.shared.baseURL)
            ])
            return true
        } catch {
            if reportError { lastError = error.localizedDescription }
            return false
        }
    }

    func register(username: String, password: String, organizationId: String) async -> Bool {
        isWorking = true; lastError = nil
        defer { isWorking = false }
        do {
            let resp = try await api.register(
                username: username,
                password: password,
                organizationId: organizationId
            )
            if resp.success {
                seedUser(from: resp, fallbackUsername: username)
                try? CanonicalFactorLibraryAccessStore.ensureDefault(
                    for: resp.username ?? username
                )
                return await completeAuthentication(
                    principalRef: resp.username ?? username,
                    username: username,
                    password: password
                )
            } else {
                lastError = resp.error ?? L10n.text("注册失败")
                return false
            }
        } catch {
            lastError = (error as? APIError)?.errorDescription ?? error.localizedDescription
            return false
        }
    }

    private func completeAuthentication(
        principalRef: String,
        username: String,
        password: String
    ) async -> Bool {
        do {
            let confirmed = try await confirmPersistentSession()
            user = confirmed
            try? CanonicalFactorLibraryAccessStore.ensureDefault(
                for: confirmed.username ?? principalRef
            )
        } catch {
            clearAuthentication()
            lastError = L10n.format(
                "登录状态未能持久化：%@",
                error.localizedDescription
            )
            return false
        }
        let credentialsPersisted = saveCredentials(
            username: username,
            password: password
        )
        do {
            try await managerAPI.login(username: username, password: password)
            isManagerLoggedIn = true
        } catch {
            isManagerLoggedIn = false
            // Manager 是所有客户端模块的统一入口；暂时不可用不能反向使
            // 已成功的业务端口登录失效，页面会明确显示入口不可用。
            lastError = L10n.format(
                "Manager 暂时不可用，主登录仍保持有效：%@",
                error.localizedDescription
            )
        }
        if !credentialsPersisted && lastError == nil {
            lastError = L10n.text(
                "登录成功，但本机凭证未能保存；重启后可能需要重新登录"
            )
        }
        _ = await bridgeClientSession(
            principalRef: principalRef,
            reportError: false
        )
        return true
    }

    private func confirmPersistentSession() async throws -> UserInfo {
        var persistenceError: Error?
        do {
            try await api.setKeepLogin(true)
        } catch {
            persistenceError = error
        }
        let confirmed = try await api.me()
        guard confirmed.isLoggedIn, confirmed.keepLogin else {
            if let persistenceError { throw persistenceError }
            throw APIError.server(
                L10n.text("服务器未确认保持登录状态")
            )
        }
        return confirmed
    }

    @discardableResult
    private func saveCredentials(username: String, password: String) -> Bool {
        credentialSaver(username, password)
    }

    private func restoreSavedSessionWithRetry() async -> Bool {
        if let restoreTask {
            return await restoreTask.value
        }
        let task = Task { @MainActor [weak self] in
            guard let self else { return false }
            return await self.performRestoreSavedSessionWithRetry()
        }
        restoreTask = task
        let restored = await task.value
        restoreTask = nil
        return restored
    }

    private func performRestoreSavedSessionWithRetry() async -> Bool {
        if await restoreSavedSessionAttempt() { return true }
        guard credentialLoader() != nil else { return false }
        for delay in [500_000_000, 1_000_000_000] {
            try? await Task.sleep(nanoseconds: UInt64(delay))
            if await restoreSavedSessionAttempt() { return true }
            guard credentialLoader() != nil else {
                return false
            }
        }
        return false
    }

    private func restoreSavedSessionAttempt() async -> Bool {
        guard let credentials = credentialLoader() else {
            return false
        }
        do {
            let response = try await api.login(
                username: credentials.username,
                password: credentials.password
            )
            guard response.success else {
                SessionCredentialStore.clear()
                clearAuthentication()
                return false
            }
            let confirmed = try await confirmPersistentSession()
            user = confirmed
            try? CanonicalFactorLibraryAccessStore.ensureDefault(
                for: confirmed.username ?? credentials.username
            )
            await refreshManagerSession(credentials: credentials)
            let bridged = await bridgeClientSession(
                principalRef: response.username ?? credentials.username
            )
            if !bridged { lastError = nil }
            return true
        } catch let error as APIError {
            if case .unauthorized = error {
                SessionCredentialStore.clear()
                clearAuthentication()
            } else {
                lastError = error.localizedDescription
            }
            return false
        } catch {
            lastError = error.localizedDescription
            return false
        }
    }

    /// Manager sessions expire independently from the long-lived service
    /// session. Refresh the unified gateway for every authenticated user so
    /// embedded Manager pages do not disagree with the native account state.
    private func refreshManagerSession(
        credentials: SavedSessionCredentials? = nil
    ) async {
        let expectedUsername = user?.username ?? ""
        do {
            if try await managerAPI.restoreSession() {
                isManagerLoggedIn = true
                return
            }
        } catch {
            // Missing or expired Manager sessions are repaired below.  The
            // public path uses only the bound device; private LAN may use the
            // app credential already used to restore the service session.
        }
        do {
            switch try await managerDeviceSessionRestorer(expectedUsername) {
            case .authenticated(let username):
                guard !expectedUsername.isEmpty, username == expectedUsername else {
                    isManagerLoggedIn = false
                    lastError = L10n.text(
                        "当前设备绑定的用户与已登录用户不一致，已拒绝切换账号。"
                    )
                    return
                }
                isManagerLoggedIn = true
                return
            case .notRequired:
                break
            }
        } catch {
            // Public Managers accept only the approved device identity.  A
            // failed or revoked device must never fall back to a password.
            isManagerLoggedIn = false
            lastError = (error as? APIError)?.errorDescription
                ?? error.localizedDescription
            return
        }
        guard let credentials = credentials ?? credentialLoader() else {
            isManagerLoggedIn = false
            return
        }
        do {
            try await managerAPI.login(
                username: credentials.username,
                password: credentials.password
            )
            isManagerLoggedIn = true
        } catch {
            isManagerLoggedIn = false
        }
    }

    private static func restoreConfiguredPublicManagerDeviceSession(
        expectedUsername: String
    ) async throws -> ManagerDeviceSessionRestore {
        guard let endpoint = ManagerConfig.shared.baseURL,
              let host = endpoint.host,
              !ManagerEndpointPolicy.isPrivateNetwork(host) else {
            return .notRequired
        }
        let result = try await ManagerDeviceAuthenticationService.shared.authenticate(
            endpoint: endpoint,
            expectedUsername: expectedUsername
        )
        return .authenticated(username: result.username)
    }

    func logout() async {
        SessionCredentialStore.clear()
        user = nil
        isManagerLoggedIn = false
        let api = api
        let managerAPI = managerAPI
        let serverURL = ManagerConfig.shared.baseURL?.absoluteString
        let executable = ClientCLIResolution.executable()
        try? await api.logout()
        await managerAPI.logout()
        if let serverURL {
            _ = try? await ReleaseCommand.runObject([
                "client", "profile", "clear-ui-session",
                "--server-url", serverURL,
            ], executable: executable)
        }
    }

    func updateSavedPassword(_ password: String) {
        guard let username = user?.username else { return }
        if !saveCredentials(username: username, password: password) {
            lastError = L10n.text("本机凭证未能保存")
        }
    }

    func setKeepLogin(_ keep: Bool) async {
        do {
            try await api.setKeepLogin(keep)
            _ = await refresh()
        } catch {
            lastError = error.localizedDescription
        }
    }
}
