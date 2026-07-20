import Foundation
import Combine

/// 服务器连接配置 —— 用户自己填写网址与端口，持久化后可随时修改。
///
/// 存储在 UserDefaults，App 重启后保留；在「服务器设置」页面可重新编辑。
/// 这是「一套通用方法固定前端体验」的根基：所有原生页面与 web 转发页都从
/// 这里取 `baseURL`，改一处即全局生效。
final class ServerConfig: ObservableObject {

    static let shared = ServerConfig()

    private enum Keys {
        static let scheme = "server.scheme"
        static let host   = "server.host"
        static let port   = "server.port"
    }

    /// http / https。自签名服务器多为 https，App 已放行自签名证书。
    @Published var scheme: String {
        didSet { UserDefaults.standard.set(scheme, forKey: Keys.scheme) }
    }
    /// 主机名或 IP，例如 192.168.1.10 或 my-server.local
    @Published var host: String {
        didSet { UserDefaults.standard.set(host, forKey: Keys.host) }
    }
    /// 端口，例如 8000。留空表示使用协议默认端口。
    @Published var port: String {
        didSet { UserDefaults.standard.set(port, forKey: Keys.port) }
    }

    private init() {
        let d = UserDefaults.standard
        scheme = d.string(forKey: Keys.scheme) ?? "http"
        host   = d.string(forKey: Keys.host) ?? "127.0.0.1"
        port   = d.string(forKey: Keys.port) ?? "8000"
    }

    /// 是否已填写过有效服务器地址。
    var isConfigured: Bool {
        !host.trimmingCharacters(in: .whitespaces).isEmpty
    }

    /// 拼出根 URL，例如 http://192.168.1.10:8000
    var baseURL: URL? {
        let trimmedHost = host.trimmingCharacters(in: .whitespaces)
        guard !trimmedHost.isEmpty else { return nil }
        var components = URLComponents()
        components.scheme = scheme
        components.host = trimmedHost
        let trimmedPort = port.trimmingCharacters(in: .whitespaces)
        if let p = Int(trimmedPort) { components.port = p }
        return components.url
    }

    /// 在 baseURL 之上拼接服务器路径（如 "/single_factor_test"）。
    func url(forPath path: String) -> URL? {
        guard let base = baseURL else { return nil }
        return URL(string: path, relativeTo: base)?.absoluteURL
    }

    /// 校验后保存（trim 主机名）。
    func save(scheme: String, host: String, port: String) {
        self.scheme = scheme
        self.host = host.trimmingCharacters(in: .whitespaces)
        self.port = port.trimmingCharacters(in: .whitespaces)
    }
}
