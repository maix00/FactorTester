import Foundation

struct LocalAgentModel: Identifiable {
    let id: String
    let role: String
    let scope: String

    init(json: [String: Any]) {
        id = json["agent_id"] as? String ?? ""
        role = json["role"] as? String ?? ""
        let values = json["scope"] as? [String: Any] ?? [:]
        scope = values.keys.sorted().compactMap { key in
            guard let value = values[key] as? String else { return nil }
            return "\(key): \(value)"
        }.joined(separator: " · ")
    }
}

struct LocalProfileModel: Identifiable {
    let id: String
    let displayName: String
    let serverURL: String
    let workspaceRoot: String
    let agents: [LocalAgentModel]

    init(json: [String: Any]) {
        id = json["profile_id"] as? String ?? ""
        displayName = json["display_name"] as? String ?? id
        serverURL = (json["server"] as? [String: Any])?["base_url"]
            as? String ?? ""
        workspaceRoot = json["workspace_root"] as? String ?? ""
        agents = (json["agents"] as? [[String: Any]] ?? [])
            .map(LocalAgentModel.init)
    }
}
