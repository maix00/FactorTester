import Foundation
import Combine

final class ManagerConfig: ObservableObject {
    static let shared = ManagerConfig()

    /// The only endpoint embedded in a released Swift client.  It is used
    /// solely as a discovery seed; the active Manager is selected from the
    /// server-provided online candidates at launch.  Update this value before
    /// building a release when the bootstrap public IP changes.
    static let bakedPublicBootstrapEndpoint = URL(
        string: "https://101.133.144.27:7998"
    )!

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
        serverID = defaults.string(forKey: Keys.serverID) ?? ""
        let storedHost = defaults.string(forKey: Keys.host) ?? ""
        let storedSource = defaults.string(forKey: Keys.selectionSource)
            .flatMap(SelectionSource.init(rawValue:))
        let source = storedSource ?? (
            storedHost.isEmpty || ManagerEndpointPolicy.isLoopback(storedHost)
                ? .automatic
                : .manual
        )
        selectionSource = source

        if source == .automatic {
            // Automatic mode always starts from the baked public seed. This
            // lets a rebuilt client discover a changed public IP instead of
            // becoming stuck on a previously selected internal/remote host.
            scheme = Self.bakedPublicBootstrapEndpoint.scheme ?? "https"
            host = Self.bakedPublicBootstrapEndpoint.host ?? ""
            port = String(Self.bakedPublicBootstrapEndpoint.port ?? 7998)
        } else {
            scheme = defaults.string(forKey: Keys.scheme) ?? "http"
            host = storedHost
            port = defaults.string(forKey: Keys.port) ?? "7998"
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

    /// Automatic mode is driven by the baked public seed and server-provided
    /// candidates. A manually entered single endpoint disables switching.
    var shouldDiscoverNearestPublicManager: Bool {
        selectionSource == .automatic
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
