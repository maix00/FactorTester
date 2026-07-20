import Foundation

struct ClientAdapterModel: Identifiable {
    let id: String
    let displayName: String
    let version: String
    let uiURL: URL?
    let running: Bool
    let healthy: Bool

    init(json: [String: Any]) {
        id = json["adapter_id"] as? String ?? ""
        displayName = json["display_name"] as? String ?? id
        version = json["version"] as? String ?? ""
        running = json["running"] as? Bool ?? false
        healthy = json["healthy"] as? Bool ?? false
        uiURL = Self.loopbackURL(json["ui_url"] as? String ?? "")
    }

    private static func loopbackURL(_ value: String) -> URL? {
        guard
            let url = URL(string: value),
            ["http", "https"].contains(url.scheme?.lowercased() ?? ""),
            ["127.0.0.1", "localhost", "::1"].contains(
                url.host?.lowercased() ?? ""
            )
        else { return nil }
        return url
    }
}
