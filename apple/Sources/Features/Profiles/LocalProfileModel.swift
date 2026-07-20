import Foundation

struct LocalWorkspaceModel: Identifiable {
    let id: String
    let path: String
    let accessMode: String
    let ownerRef: String
    let serverWorkspaceRef: String

    init(json: [String: Any]) {
        id = json["workspace_id"] as? String ?? ""
        path = json["path"] as? String ?? ""
        accessMode = json["access_mode"] as? String ?? ""
        ownerRef = json["owner_ref"] as? String ?? ""
        serverWorkspaceRef = json["server_workspace_ref"] as? String ?? ""
    }
}

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

struct LocalInitializationSourceModel: Identifiable {
    let id: String
    let ownerRef: String
    let mode: String
    let sourceRef: String

    init(json: [String: Any]) {
        id = json["source_id"] as? String ?? ""
        ownerRef = json["owner_ref"] as? String ?? ""
        mode = json["mode"] as? String ?? ""
        sourceRef = json["source_ref"] as? String ?? ""
    }
}

struct LocalProfileModel: Identifiable {
    let id: String
    let displayName: String
    let serverURL: String
    let workspaceRoot: String
    let workspaces: [LocalWorkspaceModel]
    let initializationSources: [LocalInitializationSourceModel]
    let agents: [LocalAgentModel]
    let principalRef: String
    let researchRecords: [ResearchRecordModel]

    init(json: [String: Any]) {
        id = json["profile_id"] as? String ?? ""
        displayName = json["display_name"] as? String ?? id
        serverURL = (json["server"] as? [String: Any])?["base_url"]
            as? String ?? ""
        workspaceRoot = json["workspace_root"] as? String ?? ""
        principalRef = (
            json["session_binding"] as? [String: Any]
        )?["principal_ref"] as? String ?? ""
        workspaces = (json["workspaces"] as? [[String: Any]] ?? [])
            .map(LocalWorkspaceModel.init)
        initializationSources = (
            json["initialization_sources"] as? [[String: Any]] ?? []
        ).map(LocalInitializationSourceModel.init)
        agents = (json["agents"] as? [[String: Any]] ?? [])
            .map(LocalAgentModel.init)
        researchRecords = (
            json["research_records"] as? [[String: Any]] ?? []
        ).map(ResearchRecordModel.init)
    }
}
