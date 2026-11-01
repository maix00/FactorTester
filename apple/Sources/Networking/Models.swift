import Foundation

/// Identity obtained from a verified Manager session, never from a web message.
struct LocalResearchIdentity: Equatable {
    let issuer: String
    let subject: String
    let stableID: String

    /// Without a verified federation proof only the same issuer and subject
    /// can identify the same person. Stable IDs from other issuers are untrusted.
    func matchesVerifiedSameRealmIdentity(_ other: LocalResearchIdentity) -> Bool {
        guard stableID == other.stableID else { return false }
        let a = issuer.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        let b = other.issuer.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        return a == b && subject == other.subject
    }
}

/// 与 Manager `/api/session`、`/auth/login`、`/auth/register` 的 JSON 契约对应。
struct UserInfo: Codable, Equatable {
    var username: String?
    var alias: String?
    var role: String?
    var organizationId: String?
    var organizationName: String?
    var isAdmin: Bool
    var isDeveloper: Bool
    var keepLogin: Bool
    var keycloakIssuer: String?
    var keycloakSubject: String?
    var stableIdentityID: String?
    var visitorLogin: Bool
    var authentication: String?

    init(
        username: String?, alias: String? = nil, role: String? = nil,
        organizationId: String? = nil, organizationName: String? = nil,
        isAdmin: Bool = false, isDeveloper: Bool = false, keepLogin: Bool = true
    ) {
        self.username = username
        self.alias = alias
        self.role = role
        self.organizationId = organizationId
        self.organizationName = organizationName
        self.isAdmin = isAdmin
        self.isDeveloper = isDeveloper
        self.keepLogin = keepLogin
        self.keycloakIssuer = nil
        self.keycloakSubject = nil
        self.stableIdentityID = nil
        self.visitorLogin = false
        self.authentication = nil
    }

    enum CodingKeys: String, CodingKey {
        case username, alias, role
        case organizationId = "organization_id"
        case organizationName = "organization_name"
        case isAdmin = "is_admin"
        case isDeveloper = "is_developer"
        case keepLogin = "keep_login"
        case keycloakIssuer = "keycloak_issuer"
        case keycloakSubject = "keycloak_subject"
        case stableIdentityID = "tr_identity_id"
        case visitorLogin = "visitor_login"
        case authentication
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
        keycloakIssuer = try c.decodeIfPresent(String.self, forKey: .keycloakIssuer)
        keycloakSubject = try c.decodeIfPresent(String.self, forKey: .keycloakSubject)
        stableIdentityID = try c.decodeIfPresent(String.self, forKey: .stableIdentityID)
        visitorLogin = (try? c.decodeIfPresent(Bool.self, forKey: .visitorLogin)) ?? false
        authentication = try c.decodeIfPresent(String.self, forKey: .authentication)
    }

    var isLoggedIn: Bool { (username?.isEmpty == false) }

    /// Missing or capability-only sessions never gain access to local research.
    var localResearchIdentity: LocalResearchIdentity? {
        guard isLoggedIn, !visitorLogin, role != "visitor", authentication != "agent",
              let issuer = keycloakIssuer?.trimmingCharacters(in: .whitespacesAndNewlines),
              let subject = keycloakSubject?.trimmingCharacters(in: .whitespacesAndNewlines),
              let stableID = stableIdentityID?.trimmingCharacters(in: .whitespacesAndNewlines),
              let url = URLComponents(string: issuer),
              ["https", "http"].contains(url.scheme?.lowercased() ?? ""),
              url.host != nil, url.user == nil, url.password == nil,
              url.query == nil, url.fragment == nil,
              !subject.isEmpty, !stableID.isEmpty,
              subject.utf8.count <= 255, stableID.utf8.count <= 128 else { return nil }
        return LocalResearchIdentity(issuer: issuer, subject: subject, stableID: stableID)
    }

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
    case unauthorized(String)
    case server(String)
    case transport(String)

    var errorDescription: String? {
        switch self {
        case .notConfigured:
            return L10n.text("尚未配置服务器地址，请先在设置中填写。")
        case .unauthorized(let m): return m
        case .server(let m): return m
        case .transport(let m): return m
        }
    }
}
