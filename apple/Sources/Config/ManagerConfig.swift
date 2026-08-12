import Foundation
import Combine

final class ManagerConfig: ObservableObject {
    static let shared = ManagerConfig()

    private enum Keys {
        static let scheme = "manager.scheme"
        static let host = "manager.host"
        static let port = "manager.port"
    }

    @Published var scheme: String {
        didSet { UserDefaults.standard.set(scheme, forKey: Keys.scheme) }
    }
    @Published var host: String {
        didSet { UserDefaults.standard.set(host, forKey: Keys.host) }
    }
    @Published var port: String {
        didSet { UserDefaults.standard.set(port, forKey: Keys.port) }
    }

    private init() {
        let defaults = UserDefaults.standard
        scheme = defaults.string(forKey: Keys.scheme) ?? "http"
        host = defaults.string(forKey: Keys.host) ?? "127.0.0.1"
        port = defaults.string(forKey: Keys.port) ?? "7998"
    }

    var baseURL: URL? {
        var components = URLComponents()
        components.scheme = scheme
        components.host = host.trimmingCharacters(in: .whitespaces)
        if let value = Int(port.trimmingCharacters(in: .whitespaces)) {
            components.port = value
        }
        return components.url
    }

    var isLoopback: Bool {
        ["127.0.0.1", "localhost", "::1"].contains(
            host.trimmingCharacters(in: .whitespaces).lowercased()
        )
    }

    var isValid: Bool {
        baseURL != nil && (isLoopback || scheme == "https")
    }

    func url(forPath path: String) -> URL? {
        guard let baseURL else { return nil }
        return URL(string: path, relativeTo: baseURL)?.absoluteURL
    }

    func save(scheme: String, host: String, port: String) {
        self.scheme = scheme
        self.host = host.trimmingCharacters(in: .whitespaces)
        self.port = port.trimmingCharacters(in: .whitespaces)
    }
}
