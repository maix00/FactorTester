import Foundation
import Combine

/// 全局登录态 —— 包装 `/api/me`、`/login`、`/logout`，供整个 App 观察。
@MainActor
final class SessionStore: ObservableObject {
    typealias ClientSessionBridge = @MainActor (String) async -> Bool

    @Published private(set) var user: UserInfo?
    @Published private(set) var isWorking = false
    @Published var lastError: String?

    private let api: any SessionAPI
    private let bridgeOverride: ClientSessionBridge?

    init(
        api: any SessionAPI = APIClient.shared,
        bridge: ClientSessionBridge? = nil
    ) {
        self.api = api
        bridgeOverride = bridge
    }

    var isLoggedIn: Bool { user?.isLoggedIn ?? false }
    var role: String? { user?.role }

    /// 启动 / 设置变更后刷新当前登录态。
    func refresh() async {
        do { user = try await api.me() }
        catch { user = nil }
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
                return await completeAuthentication(
                    principalRef: resp.username ?? username
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
                return await completeAuthentication(
                    principalRef: resp.username ?? username
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

    private func completeAuthentication(principalRef: String) async -> Bool {
        do {
            try await api.setKeepLogin(true)
        } catch {
            user = nil
            lastError = error.localizedDescription
            return false
        }
        await refresh()
        guard isLoggedIn else {
            lastError = L10n.text("登录状态未能确认，请重新登录。")
            return false
        }
        guard await bridgeClientSession(principalRef: principalRef) else {
            try? await api.logout()
            user = nil
            return false
        }
        return true
    }

    func logout() async {
        user = nil
        let api = api
        let serverURL = ServerConfig.shared.baseURL?.absoluteString
        let executable = ClientCLIResolution.executable()
        Task {
            try? await api.logout()
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
