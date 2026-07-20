import Foundation

/// 与后端 `/api/me`、`/login`、`/register` 的 JSON 契约对应。
struct UserInfo: Codable, Equatable {
    var username: String?
    var alias: String?
    var role: String?
    var organizationId: String?
    var organizationName: String?
    var isAdmin: Bool
    var isDeveloper: Bool
    var keepLogin: Bool

    enum CodingKeys: String, CodingKey {
        case username, alias, role
        case organizationId = "organization_id"
        case organizationName = "organization_name"
        case isAdmin = "is_admin"
        case isDeveloper = "is_developer"
        case keepLogin = "keep_login"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        username = try c.decodeIfPresent(String.self, forKey: .username)
        alias = try c.decodeIfPresent(String.self, forKey: .alias)
        role = try c.decodeIfPresent(String.self, forKey: .role)
        organizationId = try c.decodeIfPresent(String.self, forKey: .organizationId)
        organizationName = try c.decodeIfPresent(String.self, forKey: .organizationName)
        isAdmin = (try? c.decodeIfPresent(Bool.self, forKey: .isAdmin)) ?? false
        isDeveloper = (try? c.decodeIfPresent(Bool.self, forKey: .isDeveloper)) ?? false
        keepLogin = (try? c.decodeIfPresent(Bool.self, forKey: .keepLogin)) ?? false
    }

    var isLoggedIn: Bool { (username?.isEmpty == false) }

    /// 是否可进入「用户与机构管理」（与前端 renderUserArea 的角色判断一致）。
    var canManageUsers: Bool {
        ["super_admin", "org_admin", "level_admin"].contains(role ?? "")
    }
}

struct Organization: Codable, Identifiable, Hashable {
    let id: String
    let name: String
}

struct OrganizationsResponse: Codable {
    let success: Bool
    let organizations: [Organization]?
}

/// 登录 / 注册响应（成功时也携带用户信息）。
struct AuthResponse: Codable {
    let success: Bool
    let error: String?
    let username: String?
    let alias: String?
    let role: String?
    let isAdmin: Bool?

    enum CodingKeys: String, CodingKey {
        case success, error, username, alias, role
        case isAdmin = "is_admin"
    }
}

struct ActionResponse: Codable {
    let success: Bool
    let error: String?
}

enum APIError: LocalizedError {
    case notConfigured
    case server(String)
    case transport(String)

    var errorDescription: String? {
        switch self {
        case .notConfigured: return "尚未配置服务器地址，请先在设置中填写。"
        case .server(let m): return m
        case .transport(let m): return m
        }
    }
}
