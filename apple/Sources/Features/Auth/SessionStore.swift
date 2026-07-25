import Foundation
import Combine

/// 全局登录态 —— 包装 `/api/me`、`/login`、`/logout`，供整个 App 观察。
@MainActor
final class SessionStore: ObservableObject {
    typealias ClientSessionBridge = @MainActor (String) async -> Bool

    @Published private(set) var user: UserInfo?
    @Published private(set) var isManagerLoggedIn = false
    @Published private(set) var isWorking = false
    @Published var lastError: String?

    private let api: any SessionAPI
    private let managerAPI: any ManagerSessionAPI
    private let bridgeOverride: ClientSessionBridge?
    private var isRestoringSession = false

    init(
        api: any SessionAPI = APIClient.shared,
        managerAPI: any ManagerSessionAPI = ManagerCLIClient.shared,
        bridge: ClientSessionBridge? = nil
    ) {
        self.api = api
        self.managerAPI = managerAPI
        bridgeOverride = bridge
    }

    var isLoggedIn: Bool { user?.isLoggedIn ?? false }
    var role: String? { user?.role }

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
            user = refreshed
            if role == "super_admin" {
                isManagerLoggedIn = (try? await managerAPI.restoreSession()) == true
            } else {
                isManagerLoggedIn = false
            }
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
                saveCredentials(username: username, password: password)
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

    private func bridgeClientSession(principalRef: String) async -> Bool {
        if let bridgeOverride {
            return await bridgeOverride(principalRef)
        }
        guard let serverURL = ServerConfig.shared.baseURL?.absoluteString else {
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
                "cookies": cookies
            ])
            return true
        } catch {
            lastError = error.localizedDescription
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
                saveCredentials(username: username, password: password)
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
        try? await api.setKeepLogin(true)
        let refreshed = await refresh()
        guard refreshed && isLoggedIn else {
            lastError = L10n.text("登录状态未能确认，请重新登录。")
            return false
        }
        if role == "super_admin" {
            do {
                try await managerAPI.login(username: username, password: password)
                isManagerLoggedIn = true
            } catch {
                isManagerLoggedIn = false
                // Manager is an optional capability.  A transient manager
                // failure must not invalidate the already successful user
                // session or force a second login.
                lastError = L10n.text("Manager 暂时不可用，主登录仍保持有效：") + error.localizedDescription
            }
        } else {
            isManagerLoggedIn = false
        }
        if !(await bridgeClientSession(principalRef: principalRef)) {
            // The CLI/UI session bridge is auxiliary to the server session.
            // Keep the authenticated identity and retry the bridge on the
            // next refresh instead of logging the user out on a local error.
            lastError = L10n.text("客户端会话桥接暂时不可用，主登录仍保持有效。")
        }
        return true
    }

    private func saveCredentials(username: String, password: String) {
        SessionCredentialStore.save(
            username: username,
            password: password,
            serverURL: ServerConfig.shared.baseURL
        )
    }

    private func restoreSavedSessionWithRetry() async -> Bool {
        if await restoreSavedSession() { return true }
        guard SessionCredentialStore.hasSavedCredentials(
            serverURL: ServerConfig.shared.baseURL
        ) else { return false }
        for delay in [500_000_000, 1_000_000_000] {
            try? await Task.sleep(nanoseconds: UInt64(delay))
            if await restoreSavedSession() { return true }
            guard SessionCredentialStore.hasSavedCredentials(
                serverURL: ServerConfig.shared.baseURL
            ) else { return false }
        }
        return false
    }

    private func restoreSavedSession() async -> Bool {
        guard !isRestoringSession,
              let credentials = SessionCredentialStore.load(
                serverURL: ServerConfig.shared.baseURL
              ) else { return false }
        isRestoringSession = true
        defer { isRestoringSession = false }
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
            seedUser(from: response, fallbackUsername: credentials.username)
            try? await api.setKeepLogin(true)
            if role == "super_admin" {
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

    func logout() async {
        SessionCredentialStore.clear()
        user = nil
        isManagerLoggedIn = false
        let api = api
        let managerAPI = managerAPI
        let serverURL = ServerConfig.shared.baseURL?.absoluteString
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
        saveCredentials(username: username, password: password)
    }

    func setKeepLogin(_ keep: Bool) async {
        try? await api.setKeepLogin(keep)
        await refresh()
    }
}
