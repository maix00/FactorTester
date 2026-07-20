import Foundation

struct ResearchDeepLinkModel: Identifiable {
    let id: String
    let kind: String
    let targetRef: String
    let sectionRef: String

    init(json: [String: Any]) {
        id = json["link_id"] as? String ?? ""
        kind = json["kind"] as? String ?? ""
        targetRef = json["target_ref"] as? String ?? ""
        sectionRef = json["section_ref"] as? String ?? ""
    }
}

struct ResearchArtifactModel: Identifiable {
    let id: String
    let format: String
    let status: String
    let localRef: String
    let indexRef: String
    let sectionRefs: [ResearchDeepLinkModel]

    init(json: [String: Any]) {
        id = json["artifact_ref"] as? String ?? ""
        format = json["format"] as? String ?? ""
        status = json["status"] as? String ?? ""
        localRef = json["local_ref"] as? String ?? ""
        indexRef = json["index_ref"] as? String ?? ""
        sectionRefs = (json["section_refs"] as? [[String: Any]] ?? [])
            .map(ResearchDeepLinkModel.init)
    }
}

struct ResearchRecordModel: Identifiable {
    let id: String
    let title: String
    let status: String
    let agentID: String
    let scope: String
    let timeline: [ResearchDeepLinkModel]
    let artifacts: [ResearchArtifactModel]

    init(json: [String: Any]) {
        id = json["record_id"] as? String ?? ""
        title = json["title"] as? String ?? id
        status = json["status"] as? String ?? ""
        agentID = json["agent_id"] as? String ?? ""
        scope = String(describing: json["scope"] ?? [:])
        timeline = (json["timeline_refs"] as? [[String: Any]] ?? [])
            .map(ResearchDeepLinkModel.init)
        artifacts = (json["artifacts"] as? [[String: Any]] ?? [])
            .map(ResearchArtifactModel.init)
    }
}
