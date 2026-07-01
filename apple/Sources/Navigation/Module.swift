import Foundation

/// 一个首页模块条目 —— 与 `/static/config/modules.json` 的 schema 对应。
/// 这是跨客户端共享注册表的原生镜像；新增模块只改服务器那份 JSON，无需改 App。
struct Module: Codable, Identifiable, Hashable {
    let id: String
    let title: String
    let desc: String
    /// web 端 emoji 图标（原生端优先用 sfSymbol，这里作兜底文本）。
    let icon: String
    /// 苹果原生 SF Symbol 名称。
    let sfSymbol: String?
    /// 服务器路由，例如 "/single_factor_test"。
    let path: String
    let requiresAuth: Bool
    /// 非空时仅这些角色可见。
    let roles: [String]

    enum CodingKeys: String, CodingKey {
        case id, title, desc, icon, sfSymbol, path, requiresAuth, roles
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        title = try c.decode(String.self, forKey: .title)
        desc = try c.decodeIfPresent(String.self, forKey: .desc) ?? ""
        icon = try c.decodeIfPresent(String.self, forKey: .icon) ?? ""
        sfSymbol = try c.decodeIfPresent(String.self, forKey: .sfSymbol)
        path = try c.decode(String.self, forKey: .path)
        requiresAuth = try c.decodeIfPresent(Bool.self, forKey: .requiresAuth) ?? true
        roles = try c.decodeIfPresent([String].self, forKey: .roles) ?? []
    }

    /// 给定当前用户角色，是否对其可见。
    func isVisible(forRole role: String?) -> Bool {
        roles.isEmpty || roles.contains(role ?? "")
    }
}

struct ModuleManifest: Codable {
    let version: Int?
    let modules: [Module]
}
