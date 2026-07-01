import Foundation
import Combine

/// 全局登录态 —— 包装 `/api/me`、`/login`、`/logout`，供整个 App 观察。
@MainActor
final class SessionStore: ObservableObject {

    @Published private(set) var user: UserInfo?
    @Published private(set) var isWorking = false
    @Published var lastError: String?

    var isLoggedIn: Bool { user?.isLoggedIn ?? false }
    var role: String? { user?.role }

    /// 启动 / 设置变更后刷新当前登录态。
    func refresh() async {
        do { user = try await APIClient.shared.me() }
        catch { user = nil }
    }

    func login(username: String, password: String) async -> Bool {
        isWorking = true; lastError = nil
        defer { isWorking = false }
        do {
            let resp = try await APIClient.shared.login(username: username, password: password)
            if resp.success {
                await refresh()
                return true
            } else {
                lastError = resp.error ?? "登录失败"
                return false
            }
        } catch {
            lastError = (error as? APIError)?.errorDescription ?? error.localizedDescription
            return false
        }
    }

    func register(username: String, password: String, organizationId: String) async -> Bool {
        isWorking = true; lastError = nil
        defer { isWorking = false }
        do {
            let resp = try await APIClient.shared.register(username: username, password: password, organizationId: organizationId)
            if resp.success {
                await refresh()
                return true
            } else {
                lastError = resp.error ?? "注册失败"
                return false
            }
        } catch {
            lastError = (error as? APIError)?.errorDescription ?? error.localizedDescription
            return false
        }
    }

    func logout() async {
        try? await APIClient.shared.logout()
        user = nil
    }

    func setKeepLogin(_ keep: Bool) async {
        try? await APIClient.shared.setKeepLogin(keep)
        await refresh()
    }
}
