import Foundation

/// 与后端通信的单例。
///
/// - 用基于 cookie 的会话（与 Flask session 一致）：URLSession 默认共享
///   `HTTPCookieStorage.shared`，登录后的 cookie 会自动带上，并可桥接给
///   WebView（见 WebPageView）以实现「转发到 web 版本换页」时免重新登录。
/// - 放行自签名证书：见 `SelfSignedTrustDelegate`。
final class APIClient: NSObject {

    static let shared = APIClient()

    private let config = ServerConfig.shared
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
        if let json {
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = try JSONSerialization.data(withJSONObject: json)
        }
        do {
            let (data, _) = try await session.data(for: req)
            return data
        } catch {
            throw APIError.transport(error.localizedDescription)
        }
    }

    // ── 认证 ──────────────────────────────────────────────────────────────

    func me() async throws -> UserInfo {
        let data = try await request(path: "/api/me")
        return try decoder.decode(UserInfo.self, from: data)
    }

    func login(username: String, password: String) async throws -> AuthResponse {
        let data = try await request(path: "/login", method: "POST",
                                     json: ["username": username, "password": password])
        return try decoder.decode(AuthResponse.self, from: data)
    }

    func register(username: String, password: String, organizationId: String) async throws -> AuthResponse {
        let data = try await request(path: "/register", method: "POST",
                                     json: ["username": username, "password": password,
                                            "organization_id": organizationId])
        return try decoder.decode(AuthResponse.self, from: data)
    }

    func logout() async throws {
        _ = try await request(path: "/logout", method: "POST")
    }

    func setKeepLogin(_ keep: Bool) async throws {
        _ = try await request(path: "/api/keep_login", method: "POST", json: ["keep_login": keep])
    }

    func organizations() async throws -> [Organization] {
        let data = try await request(path: "/api/organizations")
        let resp = try decoder.decode(OrganizationsResponse.self, from: data)
        return resp.organizations ?? []
    }

    // ── 共享模块注册表 ──────────────────────────────────────────────────────

    /// 拉取与 web 端同一份 `/static/config/modules.json`，实现「一处注册、多端可见」。
    func modules() async throws -> [Module] {
        let data = try await request(path: "/static/config/modules.json")
        let manifest = try decoder.decode(ModuleManifest.self, from: data)
        return manifest.modules
    }
}
