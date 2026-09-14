import Foundation

protocol SessionAPI {
    func me() async throws -> UserInfo
    func login(username: String, password: String) async throws -> AuthResponse
    func register(
        username: String,
        password: String,
        organizationId: String
    ) async throws -> AuthResponse
    func logout() async throws
    func setKeepLogin(_ keep: Bool) async throws
}

/// 与后端通信的单例。
///
/// - 用基于 cookie 的会话（与 Flask session 一致）：URLSession 默认共享
///   `HTTPCookieStorage.shared`，登录后的 cookie 会自动带上，并可桥接给
///   WebView（见 WebPageView）以实现「转发到 web 版本换页」时免重新登录。
/// - 放行自签名证书：见 `SelfSignedTrustDelegate`。
final class APIClient: NSObject {

    static let shared = APIClient()

    private let config = ManagerConfig.shared
    private lazy var session: URLSession = {
        let cfg = URLSessionConfiguration.default
        cfg.httpCookieStorage = HTTPCookieStorage.shared
        cfg.httpCookieAcceptPolicy = .always
        cfg.requestCachePolicy = .reloadIgnoringLocalCacheData
        return URLSession(configuration: cfg, delegate: SelfSignedTrustDelegate(), delegateQueue: nil)
    }()

    private let decoder = JSONDecoder()

    // ── 通用请求 ──────────────────────────────────────────────────────────

    private func request(path: String, method: String = "GET", json: [String: Any]? = nil) async throws -> Data {
        guard let url = config.url(forPath: path) else { throw APIError.notConfigured }
        var req = URLRequest(url: url)
        req.httpMethod = method
        req.setValue("application/json", forHTTPHeaderField: "Accept")
        req.setValue("FactorTester-Swift/1", forHTTPHeaderField: "User-Agent")
        req.setValue("swift", forHTTPHeaderField: "X-FactorTester-Client")
        if path != "/auth/login", path != "/auth/register" {
            let token = ManagerSessionTokenStore.read(for: ManagerConfig.shared.baseURL)
            if !token.isEmpty {
                req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
            }
        }
        if let json {
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = try JSONSerialization.data(withJSONObject: json)
        }
        do {
            let (data, response) = try await session.data(for: req)
            guard let http = response as? HTTPURLResponse else {
                throw APIError.transport(L10n.text("服务器没有返回有效的 HTTP 响应"))
            }
            guard (200..<300).contains(http.statusCode) else {
                let detail = Self.responseMessage(data) ?? "HTTP \(http.statusCode)"
                if http.statusCode == 401 || http.statusCode == 403 {
                    throw APIError.unauthorized(detail)
                }
                throw APIError.server("HTTP \(http.statusCode)：\(detail)")
            }
            return data
        } catch let error as APIError {
            throw error
        } catch {
            throw APIError.transport(error.localizedDescription)
        }
    }

    private static func responseMessage(_ data: Data) -> String? {
        if let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            for key in ["error", "message", "detail"] {
                if let value = object[key] as? String, !value.isEmpty {
                    return value
                }
            }
        }
        guard let text = String(data: data, encoding: .utf8)?
            .trimmingCharacters(in: .whitespacesAndNewlines),
              !text.isEmpty else { return nil }
        return String(text.prefix(800))
    }

    // ── 认证 ──────────────────────────────────────────────────────────────

    func me() async throws -> UserInfo {
        let data = try await request(path: "/api/session")
        var user = try decoder.decode(UserInfo.self, from: data)
        // Manager sessions are persistent, server-expiring credentials; they
        // do not implement the legacy business listener's idle-login toggle.
        user.keepLogin = user.isLoggedIn
        user.isAdmin = user.role == "super_admin"
        user.isDeveloper = user.isAdmin || user.role == "developer"
        return user
    }

    func login(username: String, password: String) async throws -> AuthResponse {
        let data = try await request(path: "/auth/login", method: "POST",
                                     json: [
                                        "username": username,
                                        "password": password,
                                        "keep_login": true,
                                     ])
        return try decoder.decode(AuthResponse.self, from: data)
    }

    func register(username: String, password: String, organizationId: String) async throws -> AuthResponse {
        let data = try await request(path: "/auth/register", method: "POST",
                                     json: ["username": username, "password": password,
                                            "organization_id": organizationId,
                                            "keep_login": true])
        return try decoder.decode(AuthResponse.self, from: data)
    }

    func logout() async throws {
        _ = try await request(path: "/auth/logout", method: "POST")
    }

    func setKeepLogin(_ keep: Bool) async throws {
        if keep {
            _ = try await me()
        } else {
            throw APIError.server(L10n.text("Manager 不支持临时会话；如需结束会话，请退出登录。"))
        }
    }

    func changePassword(currentPassword: String, newPassword: String) async throws -> ActionResponse {
        let data = try await request(
            path: "/api/account/password",
            method: "POST",
            json: [
                "current_password": currentPassword,
                "new_password": newPassword,
            ]
        )
        return try decoder.decode(ActionResponse.self, from: data)
    }

    func organizations() async throws -> [Organization] {
        let data = try await request(path: "/api/organizations")
        let resp = try decoder.decode(OrganizationsResponse.self, from: data)
        return resp.organizations ?? []
    }

    // ── 共享模块注册表 ──────────────────────────────────────────────────────

    private func managerRequest(path: String) async throws -> Data {
        guard let url = ManagerConfig.shared.url(forPath: path) else {
            throw APIError.notConfigured
        }
        var req = URLRequest(url: url)
        req.httpMethod = "GET"
        req.setValue("application/json", forHTTPHeaderField: "Accept")
        req.setValue("FactorTester-Swift/1", forHTTPHeaderField: "User-Agent")
        let token = ManagerSessionTokenStore.read(for: ManagerConfig.shared.baseURL)
        if !token.isEmpty {
            req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        let (data, response) = try await session.data(for: req)
        guard let http = response as? HTTPURLResponse else {
            throw APIError.transport(L10n.text("服务器没有返回有效的 HTTP 响应"))
        }
        guard (200..<300).contains(http.statusCode) else {
            throw APIError.server("HTTP \(http.statusCode)：\(Self.responseMessage(data) ?? "Manager 模块目录不可用")")
        }
        return data
    }

    /// 从 Manager 7998 拉取按当前会话过滤后的统一导航注册表，避免把
    /// 模块目录绑定到任意一个业务服务端口或由 Swift 自行维护权限。
    func modules() async throws -> [Module] {
        let data = try await managerRequest(path: "/api/modules")
        let manifest = try decoder.decode(ModuleManifest.self, from: data)
        return manifest.modules
    }

}

extension APIClient: SessionAPI {}
