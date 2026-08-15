import Foundation
import Combine

final class ManagerConfig: ObservableObject {
    static let shared = ManagerConfig()

    enum SelectionSource: String {
        case automatic
        case manual
    }

    private enum Keys {
        static let scheme = "manager.scheme"
        static let host = "manager.host"
        static let port = "manager.port"
        static let serverID = "manager.server-id"
        static let selectionSource = "manager.selection-source"
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
    @Published var serverID: String {
        didSet { UserDefaults.standard.set(serverID, forKey: Keys.serverID) }
    }
    @Published private(set) var selectionSource: SelectionSource

    private init() {
        let defaults = UserDefaults.standard
        scheme = defaults.string(forKey: Keys.scheme) ?? "http"
        let storedHost = defaults.string(forKey: Keys.host) ?? "127.0.0.1"
        host = storedHost
        port = defaults.string(forKey: Keys.port) ?? "7998"
        serverID = defaults.string(forKey: Keys.serverID) ?? ""
        if let raw = defaults.string(forKey: Keys.selectionSource),
           let source = SelectionSource(rawValue: raw) {
            selectionSource = source
        } else {
            // Older clients used loopback as a bootstrap endpoint. Treat an
            // unannotated loopback setting as automatic so Docker's local
            // Manager can provide the nearest public Manager on first launch.
            selectionSource = ManagerEndpointPolicy.isLoopback(storedHost)
                ? .automatic : .manual
        }
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
        ManagerEndpointPolicy.isLoopback(host)
    }

    var isPrivateNetwork: Bool {
        ManagerEndpointPolicy.isPrivateNetwork(host)
    }

    var isValid: Bool {
        baseURL != nil && (isPrivateNetwork || scheme == "https")
    }

    /// The loopback Manager is only a discovery bootstrap. Once a server has
    /// supplied a public target, the target remains the active Manager until
    /// the user explicitly edits the connection in Settings.
    var shouldDiscoverNearestPublicManager: Bool {
        selectionSource == .automatic && isLoopback
    }

    func url(forPath path: String) -> URL? {
        guard let baseURL else { return nil }
        return URL(string: path, relativeTo: baseURL)?.absoluteURL
    }

    func save(
        scheme: String,
        host: String,
        port: String,
        serverID: String? = nil,
        source: SelectionSource = .manual
    ) {
        self.scheme = scheme
        self.host = host.trimmingCharacters(in: .whitespaces)
        self.port = port.trimmingCharacters(in: .whitespaces)
        if let serverID {
            self.serverID = serverID.trimmingCharacters(in: .whitespaces)
        }
        selectionSource = source
        UserDefaults.standard.set(source.rawValue, forKey: Keys.selectionSource)
    }

    func saveAutoDiscovered(endpoint: URL, serverID: String) {
        save(
            scheme: endpoint.scheme ?? "https",
            host: endpoint.host ?? "",
            port: String(endpoint.port ?? 443),
            serverID: serverID,
            source: .automatic
        )
    }
}
