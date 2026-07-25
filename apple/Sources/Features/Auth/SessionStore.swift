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
            try await api.setKeepLogin(true)
        } catch {
            clearAuthentication()
            lastError = error.localizedDescription
            return false
        }
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
                try? await api.logout()
                user = nil
                isManagerLoggedIn = false
                lastError = L10n.text("Manager 登录失败：") + error.localizedDescription
                return false
            }
        } else {
            isManagerLoggedIn = false
        }
        guard await bridgeClientSession(principalRef: principalRef) else {
            try? await api.logout()
            await managerAPI.logout()
            user = nil
            isManagerLoggedIn = false
            return false
        }
        return true
    }

    func logout() async {
        user = nil
        isManagerLoggedIn = false
        let api = api
        let managerAPI = managerAPI
        let serverURL = ServerConfig.shared.baseURL?.absoluteString
        let executable = ClientCLIResolution.executable()
        Task {
            try? await api.logout()
            await managerAPI.logout()
            if let serverURL {
                _ = try? await ReleaseCommand.runObject([
                    "client", "profile", "clear-ui-session",
                    "--server-url", serverURL,
                ], executable: executable)
            }
        }
    }

    func setKeepLogin(_ keep: Bool) async {
        try? await api.setKeepLogin(keep)
        await refresh()
    }
}
